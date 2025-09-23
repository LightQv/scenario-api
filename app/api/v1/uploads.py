from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies import get_database, get_current_user
from app.models import User
from app.services.upload_service import UploadService

router = APIRouter(
    tags=["Uploads"],
    responses={
        404: {"description": "File not found"},
        403: {"description": "Access forbidden"},
        400: {"description": "Bad request"},
    },
)


@router.get(
    "/banner/{user_id}",
    response_class=FileResponse,
    summary="Get profile banner",
    description="Retrieve a user's profile banner image file",
)
async def get_profile_banner(
    user_id: UUID, database_session: Session = Depends(get_database)
):
    """
    Get user's profile banner image file.

    Retrieves and serves the profile banner image file for any user.
    This endpoint is public and doesn't require authentication.

    Args:
        user_id: UUID of the user whose banner to retrieve
        database_session: Database session dependency

    Returns:
        FileResponse: The banner image file

    Raises:
        HTTPException:
            - 404 if user or banner not found
    """
    # Get user from database
    user = database_session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Check if user has a banner
    if not user.profile_banner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No profile banner found for this user",
        )

    # Get file path
    file_path = UploadService.get_profile_banner_path(str(user_id), user.profile_banner)
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Banner file not found on disk",
        )

    return FileResponse(
        path=file_path, media_type="image/jpeg", filename=f"banner_{user.username}"
    )


@router.post(
    "/banner/{user_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Upload profile banner",
    description="Upload a new profile banner image for the authenticated user",
)
async def upload_profile_banner(
    user_id: UUID,
    file: UploadFile = File(..., description="Image file (JPG, PNG, WEBP, max 5MB)"),
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
):
    """
    Upload profile banner for authenticated user.

    Allows authenticated users to upload a profile banner image.
    The image will be validated, processed, and stored securely.
    If a previous banner exists, it will be replaced.

    Args:
        user_id: UUID of the user (must match authenticated user)
        file: Image file to upload (JPG, PNG, WEBP, max 5MB)
        current_user: Currently authenticated user
        database_session: Database session dependency

    Returns:
        dict: Success message with upload details

    Raises:
        HTTPException:
            - 403 if user tries to upload for someone else
            - 404 if user doesn't exist
            - 400 if file validation fails
            - 500 if upload fails
    """
    # Verify user is uploading their own banner
    if str(current_user.id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to upload for this user",
        )

    # Verify user exists in database
    user = database_session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Upload file and get filename
    filename = UploadService.upload_profile_banner(str(user_id), file)

    # Update user's profile_banner field with the filename
    user.profile_banner = filename
    database_session.commit()

    return {"message": "Profile banner uploaded successfully", "filename": filename}


@router.delete(
    "/banner/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete profile banner",
    description="Delete the profile banner for the authenticated user",
)
async def delete_profile_banner(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
):
    """
    Delete user's profile banner.

    Removes the profile banner image file and updates the database.
    Users can only delete their own banners.

    Args:
        user_id: UUID of the user (must match authenticated user)
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 403 if user tries to delete someone else's banner
            - 404 if user or banner not found
    """
    # Verify user is deleting their own banner
    if str(current_user.id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this user's banner",
        )

    # Get user from database
    user = database_session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Check if user has a banner
    if not user.profile_banner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No profile banner to delete"
        )

    # Delete file from disk
    UploadService.delete_profile_banner(str(user_id), user.profile_banner)

    # Update database
    user.profile_banner = None
    database_session.commit()
