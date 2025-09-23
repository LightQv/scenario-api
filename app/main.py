"""
Main FastAPI application module.

This module sets up the FastAPI application with all necessary middleware,
exception handlers, and route configurations. It serves as the entry point
for the Scenario API application.
"""

from fastapi import FastAPI

from app.core.exception_handlers import register_exception_handlers
from app.core.middleware import setup_cors
from app.core.settings import settings
from app.api.v1.router import main_router

# Create the FastAPI application instance
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    description="""
    🎬 **Scenario API** - A modern FastAPI application for managing movie and TV show watchlists.

    ## Features

    * **User Management**: Complete user registration, authentication, and profile management
    * **Watchlist Management**: Create and organize personalized watchlists
    * **Media Tracking**: Add movies and TV shows from TMDB to your watchlists
    * **Viewing History**: Track what you've watched with detailed statistics
    * **Statistics**: Analyze your viewing habits with comprehensive analytics
    * **Secure Authentication**: JWT-based authentication with HTTP-only cookies

    ## Authentication

    Most endpoints require authentication. Use the `/auth/login` endpoint to authenticate
    and receive a secure cookie for subsequent requests.
    """,
    contact={
        "name": "Scenario API Support",
        "url": "https://github.com/LightQv/scenario-fast-api",
        "email": settings.MAIL_FROM,
    },
    license_info={
        "name": "ISC License",
        "url": "https://opensource.org/licenses/ISC",
    },
)

# Setup CORS middleware
setup_cors(app=app)

# Include API routes
app.include_router(main_router, prefix="/api/v1")

# Register exception handlers
register_exception_handlers(app)


@app.get(
    "/",
    summary="API Root",
    description="Welcome endpoint providing basic API information and navigation links",
    tags=["Root"],
)
def read_root():
    """
    API root endpoint.

    Provides basic information about the Scenario API including version,
    documentation links, and welcome message for new users.

    Returns:
        dict: Welcome message with API information and useful links
    """
    return {
        "message": "Welcome to Scenario API",
        "version": settings.APP_VERSION,
        "description": "A modern FastAPI application for managing movie and TV show watchlists",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


@app.get(
    "/health",
    summary="Health Check",
    description="Simple health check endpoint for monitoring and load balancers",
    tags=["Health"],
)
def health_check():
    """
    Health check endpoint.

    Simple endpoint to verify that the API is running and responsive.
    Used by monitoring systems, load balancers, and container orchestration
    platforms to ensure the application is healthy.

    Returns:
        dict: Health status confirmation
    """
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
