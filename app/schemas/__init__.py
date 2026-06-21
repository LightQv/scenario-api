from app.schemas.auth import UserRegister, UserLogin, PasswordReset, ForgottenPassword, Token
from app.schemas.user import (
    UserCreate, UserUpdate, UserUpdateEmail, UserUpdatePassword,
    UserUpdateBanner, UserResponse, UserPublic, UserBanner
)
from app.schemas.watchlist import (
    WatchlistCreate, WatchlistUpdate, WatchlistResponse, WatchlistDetail, MediaInWatchlist
)
from app.schemas.media import MediaCreate, MediaUpdate, MediaResponse
from app.schemas.bookmark import BookmarkCreate
from app.schemas.view import ViewCreate, ViewResponse, ViewCountByType, ViewCountByYear, ViewRuntime
from app.schemas.owned_media import (
    OwnedMediaResponse, OwnedMediaStatusResponse, OwnedMediaSyncResponse,
    OwnedMediaSyncStatusResponse, RadarrWebhookPayload, RadarrWebhookResponse
)
from app.schemas.download_request import (
    DownloadRequestResponse, RadarrMovieDownloadCreate
)

__all__ = [
    "UserRegister", "UserLogin", "PasswordReset", "ForgottenPassword", "Token",
    "UserCreate", "UserUpdate", "UserUpdateEmail", "UserUpdatePassword",
    "UserUpdateBanner", "UserResponse", "UserPublic", "UserBanner",
    "WatchlistCreate", "WatchlistUpdate", "WatchlistResponse", "WatchlistDetail", "MediaInWatchlist",
    "MediaCreate", "MediaUpdate", "MediaResponse",
    "BookmarkCreate",
    "ViewCreate", "ViewResponse", "ViewCountByType", "ViewCountByYear", "ViewRuntime",
    "OwnedMediaResponse", "OwnedMediaStatusResponse", "OwnedMediaSyncResponse",
    "OwnedMediaSyncStatusResponse", "RadarrWebhookPayload", "RadarrWebhookResponse",
    "DownloadRequestResponse", "RadarrMovieDownloadCreate"
]
