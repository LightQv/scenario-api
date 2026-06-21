"""
Radarr integration service.

This module wraps pyarr so the rest of the application does not depend on the
third-party client API directly. It currently exposes the read-only movie
library data needed to build Scenario's owned media table.
"""

from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status

from app.core.settings import settings


class RadarrService:
    """Client wrapper for Radarr movie library operations."""

    def __init__(self, url: str | None = None, api_key: str | None = None):
        self.url: str = (url or settings.RADARR_URL).rstrip("/")
        self.api_key: str = api_key or settings.RADARR_API_KEY

    def get_movies(self) -> list[dict[str, Any]]:
        """
        Fetch the movies currently known by this Radarr library.

        Returns:
            list[dict[str, Any]]: Radarr movie payloads from the local library.

        Raises:
            HTTPException: If Radarr is not configured or the request fails.
        """
        try:
            movies = self._client().movie.get()
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to fetch Radarr movie library",
            ) from error

        if not isinstance(movies, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Radarr movie library response",
            )

        return movies

    def get_movie_by_tmdb_id(self, tmdb_id: int) -> dict[str, Any] | None:
        """Return an existing Radarr movie by TMDB ID if present."""
        for movie in self.get_movies():
            if movie.get("tmdbId") == tmdb_id:
                return movie
        return None

    def lookup_movie_by_tmdb_id(self, tmdb_id: int) -> dict[str, Any]:
        """Lookup a movie in Radarr by TMDB ID."""
        try:
            results = self._client().movie.lookup(term=f"tmdb:{tmdb_id}")
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to lookup movie in Radarr",
            ) from error

        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Movie was not found by Radarr",
            )

        return results[0]

    def add_movie_and_search(
        self,
        tmdb_id: int,
        tag_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a movie to Radarr and trigger automatic search.

        If the movie already exists in Radarr, this method queues a search for
        the existing Radarr movie instead of attempting a duplicate add.
        """
        tag_ids = self._resolve_tag_ids(tag_labels or [])
        existing_movie = self.get_movie_by_tmdb_id(tmdb_id)
        if existing_movie:
            if tag_ids:
                existing_movie = self._ensure_movie_tags(existing_movie, tag_ids)
            radarr_movie_id = existing_movie.get("id")
            if radarr_movie_id:
                self.search_movie(int(radarr_movie_id))
            return existing_movie

        movie = self.lookup_movie_by_tmdb_id(tmdb_id)

        try:
            return self._client().movie.add(
                movie=movie,
                root_dir=settings.RADARR_ROOT_FOLDER_PATH,
                quality_profile_id=settings.RADARR_QUALITY_PROFILE_ID,
                monitored=True,
                search_for_movie=True,
                monitor="movieOnly",
                minimum_availability=settings.RADARR_MINIMUM_AVAILABILITY,
                tags=tag_ids or None,
            )
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to add movie to Radarr",
            ) from error

    def search_movie(self, radarr_movie_id: int) -> dict[str, Any] | None:
        """Queue an automatic Radarr search for an existing movie."""
        try:
            return self._client().command.execute(
                "MoviesSearch",
                movieIds=[radarr_movie_id],
            )
        except Exception:
            try:
                return self._client().command.execute(
                    "MovieSearch",
                    movieId=radarr_movie_id,
                )
            except Exception as error:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unable to trigger Radarr movie search",
                ) from error

    def get_queue(self) -> list[dict[str, Any]]:
        """Return current Radarr queue records."""
        if not self.url or not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Radarr integration is not configured",
            )

        try:
            response = httpx.get(
                f"{self.url}/api/v3/queue",
                params={
                    "page": 1,
                    "pageSize": 100,
                    "includeUnknownMovieItems": "true",
                },
                headers={"X-Api-Key": self.api_key},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to fetch Radarr queue",
            ) from error

        records = payload.get("records", [])
        if not isinstance(records, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Radarr queue response",
            )

        return records

    def _resolve_tag_ids(self, tag_labels: list[str]) -> list[int]:
        """Return Radarr tag IDs, creating missing tags when necessary."""
        tag_ids: list[int] = []
        for label in tag_labels:
            tag_id = self._get_or_create_tag_id(label)
            if tag_id is not None:
                tag_ids.append(tag_id)
        return tag_ids

    def _get_or_create_tag_id(self, label: str) -> int | None:
        """Return a Radarr tag ID for one label, creating it if missing."""
        normalized_label = label.strip().lower()
        if not normalized_label:
            return None

        try:
            tags = self._client().tag.get()
            for tag in tags:
                if str(tag.get("label") or "").lower() == normalized_label:
                    return int(tag["id"])

            created_tag = self._client().tag.create(normalized_label)
            return int(created_tag["id"])
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to resolve Radarr tag",
            ) from error

    def _ensure_movie_tags(
        self,
        movie: dict[str, Any],
        tag_ids: list[int],
    ) -> dict[str, Any]:
        """Ensure an existing Radarr movie has required tags before searching."""
        existing_tag_ids = {int(tag_id) for tag_id in movie.get("tags") or []}
        required_tag_ids = set(tag_ids)
        if required_tag_ids.issubset(existing_tag_ids):
            return movie

        movie["tags"] = sorted(existing_tag_ids | required_tag_ids)
        try:
            return self._client().movie.update(movie)
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to update Radarr movie tags",
            ) from error

    def get_owned_movie_tmdb_ids(self) -> list[int]:
        """
        Return TMDB IDs for Radarr movies that have an imported file.

        Returns:
            list[int]: Unique TMDB IDs for owned movies.
        """
        owned_tmdb_ids: set[int] = set()

        for movie in self.get_movies():
            tmdb_id = movie.get("tmdbId")
            has_file = movie.get("hasFile") is True

            if has_file and tmdb_id:
                try:
                    owned_tmdb_ids.add(int(tmdb_id))
                except (TypeError, ValueError):
                    continue

        return sorted(owned_tmdb_ids)

    def _client(self):
        """Build a pyarr Radarr client from configured URL settings."""
        if not self.url or not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Radarr integration is not configured",
            )

        try:
            from pyarr import Radarr
        except ImportError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="pyarr is not installed",
            ) from error

        radarr_url = urlparse(self.url)
        host = radarr_url.hostname or self.url
        port = radarr_url.port or 7878
        tls = radarr_url.scheme == "https"
        base_path = radarr_url.path.strip("/")

        return Radarr(
            host=host,
            api_key=self.api_key,
            port=port,
            tls=tls,
            base_path=base_path,
        )
