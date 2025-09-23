"""
Database base module for SQLAlchemy ORM models.

This module provides the base class for all database models and handles
automatic model discovery for Alembic migrations. It ensures all models
inherit common functionality and timestamps.
"""

import importlib
import json
import os

from sqlalchemy import Column, DateTime, func
from sqlalchemy.orm import DeclarativeBase

from app.core.logger import log


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    This class serves as the foundation for all database models in the application.
    It provides common functionality including automatic timestamps and a standardized
    string representation for debugging purposes.

    All model classes should inherit from this base class to ensure consistency
    and compatibility with Alembic migrations.

    Attributes:
        created_at: Timestamp when the record was created
        updated_at: Timestamp when the record was last updated
    """

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self):
        """
        Return a detailed string representation of the model instance.

        Creates a JSON-formatted string representation showing all column
        values for the model instance. Useful for debugging and logging.

        Returns:
            str: Formatted string representation of the model

        Example:
            >>> user = User(username="john", email="john@example.com")
            >>> print(repr(user))
            User(
            {
              "id": "123e4567-e89b-12d3-a456-426614174000",
              "username": "john",
              "email": "john@example.com",
              "created_at": "2023-10-01T12:00:00"
            }
            )
        """
        data: dict = {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
        return (
            f"{self.__class__.__name__}(\n{json.dumps(data, indent=2, default=str)}\n)"
        )


def import_models():
    """
    Automatically import all model modules for Alembic discovery.

    This function dynamically imports all Python files in the models directory,
    ensuring that all SQLAlchemy models are properly registered with the
    DeclarativeBase. This is essential for Alembic to detect all models
    when generating migrations.

    The function scans the models directory and imports each Python module,
    excluding __init__.py and any files starting with underscore.

    Raises:
        ImportError: If any model module fails to import

    Note:
        This function is called automatically when the module is imported,
        ensuring all models are available before the application starts.
    """
    models_dir = os.path.join(os.path.dirname(__file__), "../models")
    for filename in os.listdir(models_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = f"app.models.{filename[:-3]}"
            try:
                importlib.import_module(module_name)
                log.info(f"Successfully imported model: {module_name}")
            except ImportError as error:
                log.error(f"Failed to import model: {module_name}")
                raise error


# Automatically import all models when this module is loaded
import_models()
