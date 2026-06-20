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
    media_type: str = "movie"


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
        )

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
