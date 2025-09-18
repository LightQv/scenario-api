from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import UUID

from app.api.dependencies import get_database, get_current_user
from app.core.security import hash_password
from app.models import User
from app.schemas import (
    UserPublic, UserBanner, UserUpdate, UserUpdateEmail,
    UserUpdatePassword, UserUpdateBanner
)

router = APIRouter(
    tags=["Users"],
    responses={
        404: {"description": "User not found"},
        403: {"description": "Access forbidden"}
    }
)


@router.get(
    "/{user_id}",
    response_model=UserPublic,
    summary="Get user public information",
    description="Retrieve public profile information for any user by their ID"
)
def get_user(
        user_id: UUID,
        database_session: Session = Depends(get_database)
) -> UserPublic:
    """
    Get public user information by user ID.

    Retrieves publicly visible user profile information including username,
    email, and profile banner. This endpoint doesn't require authentication
    and only returns non-sensitive user data.

    Args:
        user_id: UUID of the user to retrieve
        database_session: Database session dependency

    Returns:
        UserPublic: Public user profile information

    Raises:
        HTTPException: 404 if user doesn't exist
    """
    user = database_session.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserPublic.model_validate(user)


@router.get(
    "/banner/{user_id}",
    response_model=UserBanner,
    summary="Get user profile banner",
    description="Retrieve only the profile banner URL for a specific user"
)
def get_user_banner(
        user_id: UUID,
        database_session: Session = Depends(get_database)
) -> UserBanner:
    """
    Get user profile banner by user ID.

    Retrieves only the profile banner URL for the specified user.
    Useful for displaying user avatars/banners without fetching full profile.

    Args:
        user_id: UUID of the user whose banner to retrieve
        database_session: Database session dependency

    Returns:
        UserBanner: User profile banner information

    Raises:
        HTTPException: 404 if user doesn't exist
    """
    user = database_session.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserBanner.model_validate(user)


@router.put(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update user profile",
    description="Update complete user profile information (requires authentication)"
)
def update_user(
        user_id: UUID,
        user_data: UserUpdate,
        current_user: User = Depends(get_current_user),
        database_session: Session = Depends(get_database)
):
    """
    Update complete user profile information.

    Allows authenticated users to update their complete profile including
    username, email, and password. Users can only update their own profile.

    Args:
        user_id: UUID of the user to update
        user_data: Updated user profile data
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 403 if user tries to update someone else's profile
            - 404 if user doesn't exist
            - 400 if username or email already taken
    """
    # Verify user is updating their own profile
    if str(current_user.id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this user"
        )

    user = database_session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Update provided fields
    update_data = user_data.model_dump(exclude_unset=True)

    if "password" in update_data:
        update_data["hashed_password"] = hash_password(update_data.pop("password"))

    try:
        for field, value in update_data.items():
            setattr(user, field, value)
        database_session.commit()
    except IntegrityError:
        database_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists"
        )


@router.put(
    "/email/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update user email",
    description="Update only the user's email address (requires authentication)"
)
def update_user_email(
        user_id: UUID,
        email_data: UserUpdateEmail,
        current_user: User = Depends(get_current_user),
        database_session: Session = Depends(get_database)
):
    """
    Update user email address only.

    Allows authenticated users to update only their email address.
    The new email must be unique across the platform.

    Args:
        user_id: UUID of the user to update
        email_data: New email address data
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 403 if user tries to update someone else's email
            - 404 if user doesn't exist
            - 400 if email already exists
    """
    if str(current_user.id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this user"
        )

    user = database_session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    try:
        user.email = email_data.email
        database_session.commit()
    except IntegrityError:
        database_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists"
        )


@router.put(
    "/password/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update user password",
    description="Update only the user's password (requires authentication)"
)
def update_user_password(
        user_id: UUID,
        password_data: UserUpdatePassword,
        current_user: User = Depends(get_current_user),
        database_session: Session = Depends(get_database)
):
    """
    Update user password only.

    Allows authenticated users to change their password. The new password
    is securely hashed and any existing reset tokens are invalidated.

    Args:
        user_id: UUID of the user to update
        password_data: New password data
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 403 if user tries to update someone else's password
            - 404 if user doesn't exist
    """
    if str(current_user.id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this user"
        )

    user = database_session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user.hashed_password = hash_password(password_data.password)
    user.password_token = None  # Invalidate any reset tokens
    database_session.commit()


@router.put(
    "/banner/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update user profile banner",
    description="Update only the user's profile banner image URL"
)
def update_user_banner(
        user_id: UUID,
        banner_data: UserUpdateBanner,
        current_user: User = Depends(get_current_user),
        database_session: Session = Depends(get_database)
):
    """
    Update user profile banner only.

    Allows authenticated users to update their profile banner image URL.
    The banner URL should point to a publicly accessible image.

    Args:
        user_id: UUID of the user to update
        banner_data: New banner URL data
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 403 if user tries to update someone else's banner
            - 404 if user doesn't exist
    """
    if str(current_user.id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this user"
        )

    user = database_session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user.profile_banner = banner_data.banner_link
    database_session.commit()


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user account",
    description="Permanently delete user account and all associated data"
)
def delete_user(
        user_id: UUID,
        current_user: User = Depends(get_current_user),
        database_session: Session = Depends(get_database)
):
    """
    Delete user account permanently.

    Permanently deletes the user account and all associated data including
    watchlists, media, and viewing history. This action is irreversible.

    Args:
        user_id: UUID of the user to delete
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 403 if user tries to delete someone else's account
            - 404 if user doesn't exist
    """
    if str(current_user.id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this user"
        )

    user = database_session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    database_session.delete(user)
    database_session.commit()
