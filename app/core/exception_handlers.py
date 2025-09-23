"""
Exception Handlers
"""

# Libraries
import inspect
import sys

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette import status
from starlette.responses import JSONResponse

# Modules
from app.core.exceptions.custom_exception import CustomExceptionError
from app.core.logger import log

EXCEPTION_HANDLER_MAP = {
    "value_custom_exception_error_handler": CustomExceptionError,
    "validation_exception_handler": RequestValidationError,
    "value_error_handler": ValueError,
    "sqlalchemy_exception_handler": SQLAlchemyError,
    "global_exception_handler": Exception,
}


async def value_custom_exception_error_handler(
    _: Request,
    exception: CustomExceptionError,
) -> JSONResponse:
    """
    Global app Handler for custom exceptions.
    """
    log.warning(exception.key)
    response_content: dict = {
        "key": exception.key,
        "message": exception.message,
    }

    if exception.value is not None:
        response_content["value"] = exception.value

    return JSONResponse(
        status_code=exception.status_code,
        content=response_content,
    )


async def validation_exception_handler(
    _: Request,
    exception: RequestValidationError,
) -> JSONResponse:
    """
    Handle Pydantic validation errors using structured error definitions.
    """
    errors_list: list[dict] = exception.errors()
    formatted_errors: list[dict] = [
        {
            "location": error.get("loc", []),
            "message": error.get("msg", "Unknown validation error."),
            "type": error.get("type", "unknown_validation_error"),
        }
        for error in errors_list
    ]

    response_content: dict = {
        "detail": "Pydantic validation error",
        "errors": formatted_errors,
    }

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder(response_content),
    )


async def global_exception_handler(
    _: Request,
    exception: Exception,
) -> JSONResponse:
    """
    Global exception handler.
    This one sends an error to Sentry.
    """
    log.error(f"Unexpected error: {str(exception)}")

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "key": "internal_server_error_key",
            "message": "Internal Server Error",
        },
    )


async def value_error_handler(
    _: Request,
    exception: ValueError,
) -> JSONResponse:
    """
    Handler for value errors.
    """
    error_key = str(exception)
    log.warning(error_key)

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "key": error_key,
            "message": "An unexpected error occurred.",
        },
    )


async def sqlalchemy_exception_handler(
    _: Request,
    exception: SQLAlchemyError,
) -> JSONResponse:
    """
    Handler for SQLAlchemy errors.
    """
    log.error(f"Database error: {str(exception)}")

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "key": "database_error",
            "message": "A database error occurred.",
        },
    )


def register_exception_handlers(app: FastAPI):
    """
    Iterates through all functions in the current module and registers
    them as exception handlers if they match the naming convention.
    """
    current_module = sys.modules[__name__]
    for name, function in inspect.getmembers(
        current_module, inspect.iscoroutinefunction
    ):
        if name.endswith("_handler") and name in EXCEPTION_HANDLER_MAP:
            exception_class = EXCEPTION_HANDLER_MAP[name]
            app.add_exception_handler(exception_class, function)
