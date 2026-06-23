"""TMDB service helpers for backend-owned metadata hydration."""

from dataclasses import dataclass

import httpx

from app.core.settings import settings


@dataclass(frozen=True)
class TmdbMovieMetadata:
    """Normalized movie metadata stored in Scenario owned media rows."""

    tmdb_id: int
    genre_ids: list[int]
    poster_path: str
    backdrop_path: str
    release_date: str
    release_year: str
    runtime: int
    title: str
    original_language: str = ""
    origin_country: tuple[str, ...] = ()
    media_type: str = "movie"


@dataclass(frozen=True)
class TmdbTvMetadata:
    """Normalized TV metadata stored in Scenario owned/download rows."""

    tmdb_id: int
    genre_ids: list[int]
    poster_path: str
    backdrop_path: str
    release_date: str
    release_year: str
    runtime: int
    title: str
    original_language: str = ""
    origin_country: tuple[str, ...] = ()
    media_type: str = "tv"


class TmdbService:
    """Small TMDB API client using the app's bearer token configuration."""

    base_url = "https://api.themoviedb.org/3"

    def get_movie_metadata(self, tmdb_id: int) -> TmdbMovieMetadata:
        """Fetch and normalize movie metadata by TMDB ID.

        Args:
            tmdb_id: TMDB movie identifier.

        Returns:
            TmdbMovieMetadata: Normalized metadata for Scenario lists.

        Raises:
            RuntimeError: If TMDB cannot be reached or returns an error.
        """
        data = self._request_json(f"/movie/{tmdb_id}")
        release_date = data.get("release_date") or ""

        return TmdbMovieMetadata(
            tmdb_id=tmdb_id,
            genre_ids=[genre["id"] for genre in data.get("genres", []) if genre.get("id")],
            poster_path=data.get("poster_path") or "",
            backdrop_path=data.get("backdrop_path") or "",
            release_date=release_date,
            release_year=release_date[:4] if release_date else "",
            runtime=data.get("runtime") or 0,
            title=data.get("title") or data.get("original_title") or "",
            original_language=data.get("original_language") or "",
            origin_country=tuple(data.get("origin_country") or []),
        )

    def get_tv_metadata(self, tmdb_id: int) -> TmdbTvMetadata:
        """Fetch and normalize TV metadata by TMDB ID."""
        data = self.get_tv_details(tmdb_id)
        first_air_date = data.get("first_air_date") or ""
        runtimes = data.get("episode_run_time") or []

        return TmdbTvMetadata(
            tmdb_id=tmdb_id,
            genre_ids=[genre["id"] for genre in data.get("genres", []) if genre.get("id")],
            poster_path=data.get("poster_path") or "",
            backdrop_path=data.get("backdrop_path") or "",
            release_date=first_air_date,
            release_year=first_air_date[:4] if first_air_date else "",
            runtime=runtimes[0] if runtimes else 0,
            title=data.get("name") or data.get("original_name") or "",
            original_language=data.get("original_language") or "",
            origin_country=tuple(data.get("origin_country") or []),
        )

    def get_tv_details(self, tmdb_id: int) -> dict:
        """Return raw TMDB TV series details."""
        return self._request_json(f"/tv/{tmdb_id}")

    def get_tv_external_ids(self, tmdb_id: int) -> dict:
        """Return TMDB external IDs for a TV series."""
        return self._request_json(f"/tv/{tmdb_id}/external_ids")

    def get_tvdb_id_for_tv(self, tmdb_id: int) -> int | None:
        """Resolve a TMDB TV series ID to a TVDB series ID."""
        external_ids = self.get_tv_external_ids(tmdb_id)
        tvdb_id = external_ids.get("tvdb_id")
        if tvdb_id is None:
            return None
        return int(tvdb_id)

    def get_tmdb_tv_id_for_tvdb_id(self, tvdb_id: int) -> int | None:
        """Resolve a TVDB series ID to a TMDB TV series ID."""
        data = self._request_json(f"/find/{tvdb_id}?external_source=tvdb_id")
        tv_results = data.get("tv_results") or []
        for result in tv_results:
            tmdb_id = result.get("id")
            if tmdb_id:
                return int(tmdb_id)
        return None

    def get_tv_season_details(self, tmdb_id: int, season_number: int) -> dict:
        """Return TMDB details for a TV season."""
        return self._request_json(f"/tv/{tmdb_id}/season/{season_number}")

    def _request_json(self, path: str) -> dict:
        """Execute an authenticated TMDB GET request.

        Args:
            path: TMDB API path beginning with ``/``.

        Returns:
            dict: Parsed JSON response.

        Raises:
            RuntimeError: If TMDB cannot be reached or returns invalid JSON.
        """
        try:
            with httpx.Client(timeout=15) as client:
                response = client.get(
                    f"{self.base_url}{path}",
                    headers={
                        "Authorization": f"Bearer {settings.TMDB_API_TOKEN}",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                f"TMDB API error {error.response.status_code} for {path}"
            ) from error
        except httpx.HTTPError as error:
            raise RuntimeError(f"TMDB request failed for {path}: {error}") from error
