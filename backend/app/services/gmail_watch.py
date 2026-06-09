from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.security import TokenCipher
from app.models.user import GmailWatchState, UserRecord
from app.repositories.users import UsersRepository
from app.services.gmail_api import GmailApiClient
from app.services.google_oauth import GoogleOAuthService


class GmailWatchError(RuntimeError):
    pass


class GmailWatchService:
    def __init__(
        self,
        settings: Settings,
        users_repository: UsersRepository,
        *,
        gmail_api_client: GmailApiClient | None = None,
        google_oauth_service: GoogleOAuthService | None = None,
        token_cipher: TokenCipher | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._users_repository = users_repository
        self._gmail_api_client = gmail_api_client or GmailApiClient(settings)
        self._google_oauth_service = google_oauth_service or GoogleOAuthService(settings)
        self._token_cipher = token_cipher or TokenCipher(
            settings.token_encryption_key or settings.session_secret_key
        )
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def register_watch(self, user: UserRecord) -> GmailWatchState:
        if user.id is None:
            raise GmailWatchError("User record did not include an id.")
        refresh_token = self._decrypt_refresh_token(user)
        tokens = await self._google_oauth_service.refresh_access_token(refresh_token)
        registration = await self._gmail_api_client.watch_mailbox(tokens.access_token)

        watch_state = GmailWatchState(
            status="registered",
            history_id=registration.history_id,
            expiration=registration.expiration,
            topic_name=self._settings.gmail_pubsub_topic,
            last_registered_at=self._now(),
        )
        await self._users_repository.update_gmail_watch_state(user.id, watch_state)
        return watch_state

    async def renew_due_watches(self) -> list[GmailWatchState]:
        renew_before = self._now() + timedelta(
            seconds=self._settings.gmail_watch_renewal_window_seconds
        )
        users = await self._users_repository.list_users_needing_watch_renewal(
            renew_before
        )
        renewed: list[GmailWatchState] = []
        for user in users:
            renewed.append(await self.register_watch(user))
        return renewed

    def _decrypt_refresh_token(self, user: UserRecord) -> str:
        encrypted_refresh_token = user.oauth.refresh_token_encrypted
        if not encrypted_refresh_token:
            raise GmailWatchError("User does not have a refresh token.")
        return self._token_cipher.decrypt(encrypted_refresh_token)
