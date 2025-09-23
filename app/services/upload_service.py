import os
import shutil
import uuid
from pathlib import Path
from typing import Optional
from fastapi import UploadFile, HTTPException, status


class UploadService:
    """
    Service for handling file uploads and storage management.

    This service manages the local file system storage for user uploads,
    creating appropriate directory structures and handling file operations
    with proper error handling and security measures.

    Directory structure:
    uploads/
    └── user_{user_id}/
        ├── banner_{uuid}.{ext}
        └── ... (future file types)
    """

    UPLOADS_DIR = (
        Path("/scenario/app/uploads")
        if os.path.exists("/scenario")
        else Path("app/uploads")
    )
    ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB in bytes

    @classmethod
    def _ensure_uploads_directory(cls) -> None:
        """
        Ensure the uploads directory exists with proper permissions.

        Creates the uploads directory if it doesn't exist with appropriate
        permissions for file storage operations. Handles permission issues
        gracefully in containerized environments.

        Raises:
            HTTPException: If directory creation fails due to permissions
        """
        try:
            cls.UPLOADS_DIR.mkdir(parents=True, exist_ok=True, mode=0o755)

            # Ensure the directory is writable
            if not os.access(cls.UPLOADS_DIR, os.W_OK):
                # Try to fix permissions if possible
                try:
                    os.chmod(cls.UPLOADS_DIR, 0o755)
                except PermissionError:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Upload directory is not writable",
                    )

        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Cannot create uploads directory due to permissions",
            )

    @classmethod
    def _get_user_directory(cls, user_id: str) -> Path:
        """
        Get or create user-specific directory path.

        Returns the path to a user's upload directory, creating it if necessary.
        The directory follows the naming convention: user_{user_id}

        Args:
            user_id: UUID string of the user

        Returns:
            Path: Path object pointing to user's upload directory

        Raises:
            HTTPException: If directory creation fails
        """
        cls._ensure_uploads_directory()
        user_dir = cls.UPLOADS_DIR / f"user_{user_id}"

        try:
            user_dir.mkdir(parents=True, exist_ok=True, mode=0o755)

            # Ensure the directory is writable
            if not os.access(user_dir, os.W_OK):
                try:
                    os.chmod(user_dir, 0o755)
                except PermissionError:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"User directory is not writable: {user_dir}",
                    )

            return user_dir

        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Cannot create user directory: {user_dir}",
            )

    @classmethod
    def _validate_image_file(cls, file: UploadFile) -> None:
        """
        Validate uploaded image file.

        Checks file size, extension, and basic file properties to ensure
        the uploaded file meets security and storage requirements.

        Args:
            file: FastAPI UploadFile object to validate

        Raises:
            HTTPException: 400 if file validation fails
        """
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided"
            )

        # Check file extension
        file_extension = Path(file.filename).suffix.lower()
        if file_extension not in cls.ALLOWED_IMAGE_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Invalid file type. Allowed types: {', '.join(cls.ALLOWED_IMAGE_EXTENSIONS)}",
            )

        # Check file size
        if file.size and file.size > cls.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds maximum allowed size of {cls.MAX_FILE_SIZE // (1024 * 1024)}MB",
            )

        # Check content type
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Invalid content type. Only image files are allowed",
            )

    @classmethod
    def upload_profile_banner(cls, user_id: str, file: UploadFile) -> str:
        """
        Upload and store user profile banner.

        Validates, uploads, and stores a user's profile banner image.
        If a previous banner exists, it will be replaced. Returns the
        filename for database storage.

        Args:
            user_id: UUID string of the user
            file: FastAPI UploadFile containing the image

        Returns:
            str: Filename of the stored banner (banner_{uuid}.{ext})

        Raises:
            HTTPException: 400 if file validation fails
            HTTPException: 500 if file storage fails

        Example:
            >>> filename = UploadService.upload_profile_banner("123e4567-e89b", upload_file)
            >>> print(filename)  # "banner_456f7890-abc1.jpg"
        """
        cls._validate_image_file(file)

        try:
            # Get user directory
            user_dir = cls._get_user_directory(user_id)

            # Remove existing banner if exists
            cls.delete_profile_banner(user_id)

            # Generate unique filename
            file_extension = Path(file.filename).suffix.lower()
            banner_filename = f"banner_{uuid.uuid4()}{file_extension}"
            file_path = user_dir / banner_filename

            # Save file to disk
            try:
                with open(file_path, "wb") as buffer:
                    # Reset file position to beginning
                    file.file.seek(0)
                    shutil.copyfileobj(file.file, buffer)

                # Set proper file permissions
                os.chmod(file_path, 0o644)

            except PermissionError:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Permission denied writing to: {file_path}",
                )

            return banner_filename

        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload file: {str(e)}",
            )

    @classmethod
    def delete_profile_banner(
        cls, user_id: str, filename: Optional[str] = None
    ) -> bool:
        """
        Delete user's profile banner.

        Removes the user's profile banner from the filesystem. Can delete
        a specific banner by filename or all banners in the user directory.

        Args:
            user_id: UUID string of the user
            filename: Optional specific filename to delete

        Returns:
            bool: True if file(s) were deleted, False if no files found

        Example:
            >>> # Delete specific banner
            >>> deleted = UploadService.delete_profile_banner("123e4567", "banner_456.jpg")
            >>>
            >>> # Delete all banners for user
            >>> deleted = UploadService.delete_profile_banner("123e4567")
        """
        try:
            user_dir = cls._get_user_directory(user_id)

            if filename:
                # Delete specific file
                file_path = user_dir / filename
                if file_path.exists() and file_path.is_file():
                    file_path.unlink()
                    return True
                return False
            else:
                # Delete all banner files
                banner_files = list(user_dir.glob("banner_*"))
                for banner_file in banner_files:
                    banner_file.unlink()
                return len(banner_files) > 0

        except Exception:
            # Log the error but don't raise - deletion failures shouldn't break the app
            return False

    @classmethod
    def get_profile_banner_path(cls, user_id: str, filename: str) -> Optional[Path]:
        """
        Get the full path to a user's profile banner.

        Constructs and validates the path to a user's banner file,
        ensuring the file exists before returning the path.

        Args:
            user_id: UUID string of the user
            filename: Banner filename to locate

        Returns:
            Path: Full path to the banner file, or None if not found

        Example:
            >>> path = UploadService.get_profile_banner_path("123e4567", "banner_456.jpg")
            >>> if path:
            ...     print(f"Banner found at: {path}")
        """
        try:
            user_dir = cls._get_user_directory(user_id)
            file_path = user_dir / filename

            if file_path.exists() and file_path.is_file():
                return file_path
            return None

        except Exception:
            return None

    @classmethod
    def cleanup_user_uploads(cls, user_id: str) -> bool:
        """
        Clean up all uploads for a user.

        Removes the entire user upload directory and all its contents.
        This is typically called when a user account is deleted.

        Args:
            user_id: UUID string of the user

        Returns:
            bool: True if directory was removed, False if it didn't exist

        Example:
            >>> cleaned = UploadService.cleanup_user_uploads("123e4567-e89b")
            >>> if cleaned:
            ...     print("User uploads cleaned up successfully")
        """
        try:
            user_dir = cls._get_user_directory(user_id)
            if user_dir.exists():
                shutil.rmtree(user_dir)
                return True
            return False

        except Exception:
            return False
