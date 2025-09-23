"""
Middleware
"""

# Libraries
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

# Modules
from app.core.settings import settings


def setup_cors(app: FastAPI) -> None:
    """
    Set up CORS middleware.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Origin",
            "X-Requested-With",
            "Content-Type",
            "Accept",
            "Authorization",
            "X-CSRF-Token",
        ],
        expose_headers=["Set-Cookie"],
    )
