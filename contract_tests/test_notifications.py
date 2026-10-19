"""Hermetic notification boundaries: ownership, date semantics and safe destinations."""
import base64
import sys
from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from test_up_next import service as progress
from test_insights import stub
from app.services import release_catalog_service as catalog

# Preserve the existing hermetic bootstrap's module identities: its scoped
# sys.modules patch removes newly imported names while package attributes remain.
sys.modules.setdefault("app.services.up_next_service", progress)
sys.modules.setdefault("app.services.release_catalog_service", catalog)

fixture_settings = SimpleNamespace(WEB_PUSH_ENABLED=False, WEB_PUSH_PRIVATE_KEY="", WEB_PUSH_PUBLIC_KEY="", WEB_PUSH_SUBJECT="", INTEGRATION_SETTINGS_ENCRYPTION_KEY="")
with patch.dict(sys.modules, {"app.core.settings": stub("app.core.settings", settings=fixture_settings)}):
    from app.services import notification_service as service
    from app.api.v1.notifications import router
from app.api.dependencies import get_current_user, get_database
from app.schemas.notification import NotificationSettingsInput, SubscriptionInput, checked_endpoint


class NotificationContracts(TestCase):
    """Push is opt-in, owner-private and never a backdoor network proxy."""

    def test_provider_allowlist_blocks_ssrf_and_redirects(self) -> None:
        """Reject LAN, userinfo, lookalike suffixes, ports and non-TLS destinations."""
        for url in ["http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://192.168.20.20/x",
                    "https://fcm.googleapis.com.evil.test/x", "https://evilpush.apple.com/x",
                    "https://fcm.googleapis.com:8443/x", "https://user@fcm.googleapis.com/x", "https://web.push.apple.com/x#token"]:
            with self.assertRaises(ValueError):
                checked_endpoint(url)
        for url in ["https://fcm.googleapis.com/fcm/send/x", "https://web.push.apple.com/Q/x", "https://updates.push.services.mozilla.com/wpush/v2/x"]:
            self.assertEqual(checked_endpoint(url), url)
        session = service.PushSession()
        with patch.object(service.PushSession.__bases__[0], "request") as transport:
            session.request("POST", "https://fcm.googleapis.com/x", allow_redirects=True)
            self.assertFalse(transport.call_args.kwargs["allow_redirects"])

    def test_schedule_and_subscription_validation(self) -> None:
        """Reject unknown zones, invalid time/keys and undocumented input fields."""
        values = dict(enabled=True, timezone="Europe/Paris", delivery_time="09:00", language="en-US")
        NotificationSettingsInput(**values)
        for changes in [dict(timezone="Mars/Olympus"), dict(delivery_time="24:00"), dict(enabled="true"), dict(language="xx"), dict(extra="x")]:
            with self.assertRaises(ValidationError):
                NotificationSettingsInput(**{**values, **changes})
        key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        keys = {"p256dh": base64.urlsafe_b64encode(key).decode().rstrip("="), "auth": base64.urlsafe_b64encode(b"a" * 16).decode().rstrip("=")}
        SubscriptionInput(endpoint="https://web.push.apple.com/x", keys=keys)
        with self.assertRaises(ValidationError):
            SubscriptionInput(endpoint="https://web.push.apple.com/x", keys={**keys, "auth": "bad"})

    def test_regular_today_only_and_reversible_overrides(self) -> None:
        """Specials, future/unknown and backlog are never release-day notifications."""
        day = date(2026, 10, 20)
        payload = {"seasons": [{"season_number": 0}, {"season_number": 1}],
                   "season/0": {"episodes": [{"episode_number": 1, "air_date": day.isoformat()}]},
                   "season/1": {"episodes": [{"episode_number": 1, "air_date": "2026-10-19"}, {"episode_number": 2, "air_date": None}, {"episode_number": 3, "air_date": "2026-10-21"}]}}
        self.assertFalse(service.episode_releases_today(payload, day, date.min, {}))
        payload["season/1"]["episodes"].append({"episode_number": 4, "air_date": day.isoformat()})
        self.assertTrue(service.episode_releases_today(payload, day, date.min, {}))
        self.assertFalse(service.episode_releases_today(payload, day, date.min, {(1, 4): True}))
        self.assertFalse(service.episode_releases_today(payload, day, day, {}))
        self.assertTrue(service.episode_releases_today(payload, day, day, {(1, 4): False}))

    def test_disabled_runtime_never_touches_outbox_or_provider(self) -> None:
        """Feature remains safe on older deployments without VAPID keys."""
        db = MagicMock()
        with patch.object(service, "available", return_value=False), patch.object(service, "send_push") as sender:
            from datetime import datetime, timezone
            service.process_notifications(db, datetime.now(timezone.utc))
        db.execute.assert_not_called()
        sender.assert_not_called()

    def test_routes_require_owner_and_are_private(self) -> None:
        """A stale remembered user cannot mutate the cookie owner's preferences/devices."""
        owner = uuid4()
        app = FastAPI()
        app.include_router(router, prefix="/notifications")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=owner)
        app.dependency_overrides[get_database] = lambda: MagicMock()
        payload = dict(enabled=True, timezone="Europe/Paris", delivery_time="09:00", language="en-US")
        with TestClient(app) as client, patch.object(service, "save_preferences") as write:
            self.assertEqual(client.put("/notifications", json=payload).status_code, 403)
            self.assertEqual(client.put("/notifications", headers={"X-Scenario-Owner": str(uuid4())}, json=payload).status_code, 403)
            write.assert_not_called()
        state = dict(user_id=owner, **{**payload, "enabled": False}, available=False, public_key="", device_hashes=[])
        with TestClient(app) as client, patch.object(service, "preference_state", return_value=state):
            response = client.get("/notifications")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_generic_payload_hides_private_media_and_disables_ambient_proxy(self) -> None:
        """Provider payloads have no titles, account IDs or arbitrary click URLs."""
        key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        import json
        subscription = json.dumps({"endpoint": "https://web.push.apple.com/x", "keys": {"p256dh": base64.urlsafe_b64encode(key).decode(), "auth": base64.urlsafe_b64encode(b"a" * 16).decode()}})
        with patch.object(service, "webpush", return_value=MagicMock()) as send:
            service.send_push(subscription, "fr-FR", "2026-10-20")
        data = json.loads(send.call_args.kwargs["data"])
        self.assertEqual(set(data), {"title", "body", "tag"})
        self.assertEqual(data["title"], "Scenario")
        self.assertFalse(send.call_args.kwargs["requests_session"].trust_env)
        self.assertEqual(send.call_args.kwargs["timeout"], 10)
