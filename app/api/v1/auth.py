from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import get_database
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    generate_password_reset_token,
)
from app.models import User, Watchlist
from app.models.enums import WatchlistType
from app.schemas import (
    UserRegister,
    UserLogin,
    ForgottenPassword,
    PasswordReset,
    UserResponse,
)
from app.services.email_service import send_forgotten_password_email
from app.core.settings import settings

router = APIRouter(
    tags=["Authentication"],
    responses={
        401: {"description": "Authentication failed"},
        403: {"description": "Access forbidden"},
    },
)


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    description="Create a new user account with username, email, and password validation",
)
def register_user(
    user_data: UserRegister, database_session: Session = Depends(get_database)
) -> dict:
    """
    Register a new user account.

    Creates a new user account after validating the input data and ensuring
    the username and email are unique. The password is securely hashed using bcrypt.

    Args:
        user_data: User registration data including username, email, and passwords
        database_session: Database session dependency

    Returns:
        dict: Success message confirming user creation

    Raises:
        HTTPException: 400 if username or email already exists
    """
    # Hash the password securely
    hashed_password = hash_password(user_data.password)

    # Create the new user
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_password,
    )

    try:
        database_session.add(new_user)
        database_session.commit()
        database_session.refresh(new_user)

        # Create default "toWatch" system watchlist for the new user
        default_watchlist = Watchlist(
            title="toWatch",
            type=WatchlistType.SYSTEM.value,
            author_id=new_user.id,
        )
        database_session.add(default_watchlist)
        database_session.commit()

        return {"message": "User created successfully"}
    except IntegrityError:
        database_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists",
        )


@router.post(
    "/login",
    response_model=UserResponse,
    summary="Authenticate user login",
    description="Authenticate user with email and password, returns user data and sets authentication cookie",
)
def login_user(
    user_credentials: UserLogin,
    response: Response,
    database_session: Session = Depends(get_database),
) -> UserResponse:
    """
    Authenticate user login and set authentication cookie.

    Validates user credentials against the database and creates a JWT token
    stored in an HTTP-only cookie for secure authentication.

    Args:
        user_credentials: Login credentials (email and password)
        response: FastAPI response object to set authentication cookie
        database_session: Database session dependency

    Returns:
        UserResponse: Public user data (excluding sensitive information)

    Raises:
        HTTPException: 401 if credentials are invalid
    """
    # Find user by email
    user = (
        database_session.query(User)
        .filter(User.email == user_credentials.email)
        .first()
    )

    if not user or not verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    # Create JWT token
    access_token = create_access_token(subject=user.id)

    # Set authentication cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=not settings.DEBUG,  # HTTPS in production
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRES_IN * 60,
        samesite="lax",
    )

    return UserResponse.model_validate(user)


@router.post(
    "/forgotten-password",
    status_code=status.HTTP_200_OK,
    summary="Request password reset",
    description="Send password reset email to user's registered email address",
)
async def request_password_reset(
    email_data: ForgottenPassword, database_session: Session = Depends(get_database)
) -> dict:
    """
    Send password reset email to user.

    Generates a unique reset token and sends it to the user's email address.
    The token is stored in the database for later validation.

    Args:
        email_data: Email address of the user requesting reset
        database_session: Database session dependency

    Returns:
        dict: Confirmation message that email was sent

    Raises:
        HTTPException: 401 if user not found, 500 if email sending fails
    """
    # Find user by email
    user = database_session.query(User).filter(User.email == email_data.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    # Generate reset token
    reset_token = generate_password_reset_token()

    # Save token in database
    user.password_token = reset_token
    database_session.commit()

    # Send email
    try:
        await send_forgotten_password_email(user.email, user.username, reset_token)
        return {"message": "Password reset email sent"}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send email",
        )


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    summary="Reset user password",
    description="Reset password using the token received via email",
)
def reset_password(
    reset_data: PasswordReset, database_session: Session = Depends(get_database)
) -> dict:
    """
    Reset user password using email token.

    Validates the reset token and updates the user's password with the new
    securely hashed password. The token is invalidated after successful reset.

    Args:
        reset_data: Password reset data including new password and token
        database_session: Database session dependency

    Returns:
        dict: Success message confirming password reset

    Raises:
        HTTPException: 400 if reset token is invalid
    """
    # Find user by token
    user = (
        database_session.query(User)
        .filter(User.password_token == reset_data.password_token)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token"
        )

    # Update password and invalidate token
    user.hashed_password = hash_password(reset_data.password)
    user.password_token = None
    database_session.commit()

    return {"message": "Password reset successfully"}


@router.get(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout user",
    description="Clear authentication cookie to log out the user",
)
def logout_user(response: Response) -> dict:
    """
    Log out user by clearing authentication cookie.

    Removes the authentication cookie from the user's browser,
    effectively logging them out of the application.

    Args:
        response: FastAPI response object to delete the cookie

    Returns:
        dict: Success message confirming logout
    """
    response.delete_cookie(
        key="access_token", httponly=True, secure=not settings.DEBUG, samesite="lax"
    )

    return {"message": "Logged out successfully"}
