"""
Radarr integration service.

This module wraps pyarr so the rest of the application does not depend on the
third-party client API directly. It currently exposes the read-only movie
library data needed to build Scenario's owned media table.
"""

from typing import Any
from urllib.parse import urlparse

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

        try:
            radarr_url = urlparse(self.url)
            host = radarr_url.hostname or self.url
            port = radarr_url.port or 7878
            tls = radarr_url.scheme == "https"
            base_path = radarr_url.path.strip("/")

            radarr = Radarr(
                host=host,
                api_key=self.api_key,
                port=port,
                tls=tls,
                base_path=base_path,
            )
            movies = radarr.movie.get()
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
