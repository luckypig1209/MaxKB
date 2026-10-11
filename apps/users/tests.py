import importlib
import time
from io import StringIO
from unittest.mock import patch

from common.auth.authenticate import TokenDetails
from common.auth.common import FileToken
from common.constants.authentication_type import AuthenticationType
from common.constants.cache_version import Cache_Version
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from maxkb.const import CONFIG
from users.models import User
from users.models.external_identity import UserExternalIdentity
from users.services.portal_sso import (
    PortalSSOConfig,
    PortalSSOErrorCode,
    PortalSSOServiceError,
    PortalSSOValidationError,
    canonical_json,
    create_legacy_portal_ticket,
    create_portal_ticket,
    exchange_portal_ticket,
    legacy_portal_signature,
    sign_request,
    validate_portal_payload,
    validate_timestamp,
    verify_request_signature,
    verify_signature,
)
from users.services.session import issue_system_user_session


class RecordingCache:
    """Deterministic cache double exposing add/get/delete semantics."""

    def __init__(self):
        self.values = {}
        self.now = time.time()

    def add(self, key, value, timeout=None, version=None):
        self._purge(key)
        if key in self.values:
            return False
        self.values[key] = (value, self.now + timeout if timeout is not None else None)
        return True

    def get(self, key, default=None, version=None):
        self._purge(key)
        return self.values.get(key, (default, None))[0]

    def delete(self, key, version=None):
        self.values.pop(key, None)

    def incr(self, key, delta=1, version=None):
        self._purge(key)
        if key not in self.values:
            raise ValueError(key)
        value, expires = self.values[key]
        value = int(value) + delta
        self.values[key] = (value, expires)
        return value

    def expire(self, key):
        if key in self.values:
            value, _ = self.values[key]
            self.values[key] = (value, self.now - 1)

    def _purge(self, key):
        if key in self.values:
            _, expires = self.values[key]
            if expires is not None and expires <= self.now:
                self.values.pop(key, None)


class PortalSSOProtocolTests(TestCase):
    def test_canonical_json_and_signature_vector_is_stable(self):
        body = {
            "external_user_id": "门户用户-张三",
            "username": "zhang san",
            "display_name": "张三 / 运维",
            "email": "",
            "department_code": None,
            "target": "/opportunity",
        }
        self.assertEqual(
            canonical_json(body),
            '{"department_code":null,"display_name":"张三 / 运维","email":"",'
            '"external_user_id":"门户用户-张三","target":"/opportunity","username":"zhang san"}',
        )
        expected = sign_request(
            "vector-secret",
            "POST",
            "/admin/api/user/sso/portal/tickets",
            "bia-test",
            "1730000000000",
            "nonce-中文-0123456789abcdef",
            body,
        )
        self.assertEqual(
            expected,
            "/hbzzCn2t0eOza9k+rjWZkh7ZUl/abpGgZIoSlay2dQ=",
        )

    def test_changing_any_signed_component_invalidates_signature(self):
        body = {
            "external_user_id": "user-001",
            "username": "张三",
            "display_name": "张三",
            "email": "",
            "department_code": None,
            "target": "/opportunity",
        }
        args = {
            "method": "POST",
            "path": "/admin/api/user/sso/portal/tickets",
            "client_id": "bia-test",
            "timestamp": "1730000000000",
            "nonce": "nonce-0123456789abcdef",
            "body": body,
        }
        signature = sign_request("vector-secret", **args)
        self.assertTrue(verify_request_signature("vector-secret", signature, **args))

        mutations = [
            {**args, "body": {**body, "external_user_id": "user-002"}},
            {**args, "body": {**body, "username": "李四"}},
            {**args, "body": {**body, "display_name": "李四"}},
            {**args, "body": {**body, "email": "li@example.test"}},
            {**args, "body": {**body, "department_code": "SZFZ"}},
            {**args, "body": {**body, "target": "/home"}},
            {**args, "method": "PUT"},
            {**args, "path": "/admin/api/user/sso/portal/other"},
            {**args, "client_id": "bia-other"},
            {**args, "nonce": "nonce-abcdef0123456789"},
            {**args, "timestamp": "1730000000001"},
        ]
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                self.assertFalse(verify_request_signature("vector-secret", signature, **mutated))

    def test_signature_verification_rejects_malformed_base64_without_raising(self):
        self.assertFalse(verify_signature("vector-secret", "canonical", "not-base64!"))
        self.assertFalse(verify_signature("vector-secret", "canonical", b"\xff"))

    def test_canonical_json_handles_json_scalar_types_deterministically(self):
        self.assertEqual(
            canonical_json({"flag": True, "count": 1, "empty": None}),
            '{"count":1,"empty":null,"flag":true}',
        )

    def test_request_rejects_nonce_too_short_for_128_bits(self):
        with self.assertRaises(PortalSSOValidationError):
            sign_request(
                "vector-secret",
                "POST",
                "/admin/api/user/sso/portal/tickets",
                "bia-test",
                "1730000000000",
                "short-nonce",
                {"external_user_id": "user-001", "target": "/opportunity"},
            )

    def test_payload_and_target_validation_is_closed_and_relative(self):
        valid = validate_portal_payload(
            {"external_user_id": "user-001", "email": None, "target": "/opportunity"},
            ["/home", "/opportunity"],
        )
        self.assertEqual(valid["external_user_id"], "user-001")
        for invalid in (
            {"external_user_id": "user-001", "unexpected": "value"},
            {"external_user_id": "user-001", "target": "https://portal.example/"},
            {"external_user_id": "user-001", "target": "//portal.example/"},
            {"external_user_id": "user-001", "target": "/opportunity?next=/home"},
            {"external_user_id": "user-001", "target": "/opportunity%2F..%2Fhome"},
            {"external_user_id": "user-001", "target": "/opportunity\\records"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(PortalSSOValidationError):
                validate_portal_payload(invalid, ["/home", "/opportunity"])

    def test_timestamp_window_rejects_expired_and_future_values(self):
        now_ms = 1_730_000_000_000
        self.assertTrue(validate_timestamp(str(now_ms), now_ms=now_ms, allowed_clock_skew_seconds=60))
        with self.assertRaises(PortalSSOValidationError):
            validate_timestamp(str(now_ms - 60_001), now_ms=now_ms, allowed_clock_skew_seconds=60)
        with self.assertRaises(PortalSSOValidationError):
            validate_timestamp(str(now_ms + 60_001), now_ms=now_ms, allowed_clock_skew_seconds=60)


class PortalSSOConfigTests(TestCase):
    def test_config_is_typed_and_defaults_do_not_contain_real_endpoints(self):
        config = PortalSSOConfig.from_mapping({})
        self.assertFalse(config.enabled)
        self.assertEqual(config.allowed_targets, ("/home", "/opportunity", "/opportunity/records"))
        self.assertEqual(config.client_secret, "")

    def test_enabled_config_requires_client_id_and_secret(self):
        with self.assertRaises(PortalSSOValidationError):
            PortalSSOConfig.from_mapping({"PORTAL_SSO_ENABLED": "true"}).validate_enabled()

    def test_enabled_config_rejects_empty_targets_and_zero_ticket_ttl(self):
        with self.assertRaises(PortalSSOValidationError):
            PortalSSOConfig(
                enabled=True,
                client_id="id",
                client_secret="secret",
                ticket_ttl_seconds=0,
            )
        with self.assertRaises(PortalSSOValidationError):
            PortalSSOConfig(
                enabled=True,
                client_id="id",
                client_secret="secret",
                allowed_targets=(),
            )


class SystemUserSessionTests(TestCase):
    @patch("users.services.session.cache.set")
    def test_issued_session_matches_existing_token_contract(self, cache_set):
        user = type(
            "UserStub",
            (),
            {"id": "00000000-0000-0000-0000-000000000001", "username": "alice", "email": "alice@example.test"},
        )()
        token_data, file_token = issue_system_user_session(user)
        token = token_data["token"]
        details = TokenDetails(token).get_token_details()
        self.assertEqual(
            details,
            {
                "username": user.username,
                "id": str(user.id),
                "email": user.email,
                "type": AuthenticationType.SYSTEM_USER.value,
            },
        )
        self.assertEqual(FileToken.new_instance(file_token).type, AuthenticationType.SYSTEM_USER.value)
        cache_set.assert_called_once_with(
            token,
            user,
            timeout=CONFIG.get_session_timeout(),
            version=Cache_Version.TOKEN.get_version(),
        )


class PortalSSOStatefulTests(TestCase):
    def setUp(self):
        cache.clear()
        self.config = PortalSSOConfig(
            enabled=True,
            client_id="bia-test",
            client_secret="portal-test-secret",
            allowed_targets=("/home", "/opportunity"),
            auto_provision=True,
            ticket_ttl_seconds=60,
        )
        self.path = "/admin/api/user/sso/portal/tickets"

    def _request(self, body=None, *, nonce="nonce-0123456789abcdef", timestamp=None, signature_secret=None):
        body = body or {
            "external_user_id": "portal-user-001",
            "username": "portal-user-001",
            "display_name": "门户用户",
            "email": None,
            "department_code": "OPS",
            "target": "/opportunity",
        }
        timestamp = timestamp or str(int(time.time() * 1000))
        signature = sign_request(
            signature_secret or self.config.client_secret,
            "POST",
            self.path,
            self.config.client_id,
            timestamp,
            nonce,
            body,
        )
        return body, timestamp, nonce, signature

    def _issue(self, cache_backend=None, config=None, **kwargs):
        body, timestamp, nonce, signature = self._request(**kwargs)
        return create_portal_ticket(
            body,
            config=config or self.config,
            client_id=self.config.client_id,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
            path=self.path,
            request_id="test-request",
            rate_limit_subject="test-client",
            cache_backend=cache_backend,
        )

    def test_ticket_response_contains_portal_ticket_and_only_hash_key_is_stored(self):
        recording_cache = RecordingCache()
        ticket_data = self._issue(cache_backend=recording_cache)
        self.assertIn("ticket", ticket_data)
        self.assertIn("launch_path", ticket_data)
        self.assertIn(f"ticket={ticket_data['ticket']}", ticket_data["launch_path"])
        self.assertNotIn(self.config.client_secret, ticket_data["launch_path"])
        self.assertTrue(recording_cache.values)
        self.assertTrue(all(ticket_data["ticket"] not in key for key in recording_cache.values))

        ticket_keys = [key for key in recording_cache.values if ":ticket:" in key and ":ticket-used:" not in key]
        self.assertEqual(len(ticket_keys), 1)

        recording_cache.expire(ticket_keys[0])
        with self.assertRaises(PortalSSOServiceError) as expired:
            exchange_portal_ticket(
                ticket_data["ticket"],
                config=self.config,
                cache_backend=recording_cache,
                rate_limit_subject="expired-ticket",
            )
        self.assertEqual(expired.exception.code, PortalSSOErrorCode.TICKET_INVALID)

    def test_legacy_portal_body_uses_hmac_sha1_and_discards_password(self):
        self.assertEqual(
            legacy_portal_signature(self.config.client_secret, self.config.client_id, "1710000000000"),
            "x0MMhIPPfHSIVffj1YeT9aenuT4=",
        )
        timestamp = int(time.time() * 1000)
        signature = legacy_portal_signature(self.config.client_secret, self.config.client_id, str(timestamp))
        recording_cache = RecordingCache()
        body = {
            "mobile": "13800000000",
            "username": "portal-user",
            "password": "not-a-credential",
            "signature": signature,
            "timestamp": timestamp,
        }
        ticket_data = create_legacy_portal_ticket(
            body,
            config=self.config,
            cache_backend=recording_cache,
            rate_limit_subject="legacy-client",
        )
        self.assertIn("ticket", ticket_data)
        stored = str(recording_cache.values)
        self.assertNotIn("not-a-credential", stored)
        self.assertNotIn("13800000000", stored)
        self.assertIn("portal-user", stored)

        changed_user = {**body, "username": "other-user"}
        with self.assertRaises(PortalSSOServiceError) as replay:
            create_legacy_portal_ticket(
                changed_user,
                config=self.config,
                cache_backend=recording_cache,
                rate_limit_subject="legacy-client-2",
            )
        self.assertEqual(replay.exception.code, PortalSSOErrorCode.NONCE_REPLAY)

        bad = {**body, "signature": "not-a-valid-signature", "timestamp": timestamp + 1}
        with self.assertRaises(PortalSSOServiceError) as invalid:
            create_legacy_portal_ticket(
                bad,
                config=self.config,
                cache_backend=recording_cache,
                rate_limit_subject="legacy-client-3",
            )
        self.assertEqual(invalid.exception.code, PortalSSOErrorCode.INVALID_SIGNATURE)

    def test_nonce_replay_and_signature_timestamp_failures(self):
        self._issue()
        with self.assertRaises(PortalSSOServiceError) as replay:
            self._issue()
        self.assertEqual(replay.exception.code, PortalSSOErrorCode.NONCE_REPLAY)

        body, timestamp, nonce, signature = self._request(nonce="nonce-abcdef0123456789")
        with self.assertRaises(PortalSSOServiceError) as invalid:
            create_portal_ticket(
                {**body, "username": "tampered"},
                config=self.config,
                client_id=self.config.client_id,
                timestamp=timestamp,
                nonce=nonce,
                signature=signature,
                path=self.path,
                rate_limit_subject="test-client-2",
            )
        self.assertEqual(invalid.exception.code, PortalSSOErrorCode.INVALID_SIGNATURE)

        stale = str(int(time.time() * 1000) - 120_000)
        body, _, nonce, _ = self._request(nonce="nonce-stale-0123456789", timestamp=stale)
        signature = sign_request(
            self.config.client_secret,
            "POST",
            self.path,
            self.config.client_id,
            stale,
            nonce,
            body,
        )
        with self.assertRaises(PortalSSOServiceError) as expired:
            create_portal_ticket(
                body,
                config=self.config,
                client_id=self.config.client_id,
                timestamp=stale,
                nonce=nonce,
                signature=signature,
                path=self.path,
                rate_limit_subject="test-client-3",
            )
        self.assertEqual(expired.exception.code, PortalSSOErrorCode.TIMESTAMP_INVALID)

    def test_exchange_provisions_minimum_user_and_ticket_is_single_use(self):
        ticket_data = self._issue()
        token_data, file_token = exchange_portal_ticket(
            ticket_data["ticket"],
            config=self.config,
            request_id="exchange-request",
            rate_limit_subject="test-browser",
        )
        user = User.objects.get(username="portal-user-001")
        self.assertEqual(user.role, "USER")
        self.assertEqual(user.source, "PORTAL")
        self.assertTrue(user.is_active)
        self.assertTrue(token_data["token"])
        self.assertTrue(file_token)
        self.assertTrue(UserExternalIdentity.objects.filter(user=user, provider="PORTAL").exists())
        with self.assertRaises(PortalSSOServiceError) as replay:
            exchange_portal_ticket(
                ticket_data["ticket"],
                config=self.config,
                rate_limit_subject="test-browser-2",
            )
        self.assertEqual(replay.exception.code, PortalSSOErrorCode.TICKET_INVALID)

    def test_used_marker_atomic_add_allows_only_one_consumer(self):
        recording_cache = RecordingCache()
        ticket_data = self._issue(cache_backend=recording_cache)
        fake_user = type("FakeUser", (), {"id": "fake-user"})()
        with patch("users.services.portal_sso._resolve_portal_user", return_value=(fake_user, None)), patch(
            "users.services.session.issue_system_user_session",
            return_value=({"token": "session-token"}, "file-token"),
        ):
            exchange_portal_ticket(
                ticket_data["ticket"],
                config=self.config,
                cache_backend=recording_cache,
                rate_limit_subject="atomic-consumer-1",
            )
            with self.assertRaises(PortalSSOServiceError) as replay:
                exchange_portal_ticket(
                    ticket_data["ticket"],
                    config=self.config,
                    cache_backend=recording_cache,
                    rate_limit_subject="atomic-consumer-2",
                )
        self.assertEqual(replay.exception.code, PortalSSOErrorCode.TICKET_INVALID)

    def test_active_mapping_reuses_user_and_auto_provision_off_requires_binding(self):
        existing = User.objects.create(
            username="mapped-user",
            nick_name="Mapped User",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        identity = UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id="mapped-ext",
            user=existing,
            status=UserExternalIdentity.Status.ACTIVE,
        )
        mapped_ticket = self._issue(
            config=self.config,
            body={"external_user_id": "mapped-ext", "target": "/opportunity"},
            nonce="nonce-mapped-0123456789",
        )
        token_data, _ = exchange_portal_ticket(
            mapped_ticket["ticket"], config=self.config, rate_limit_subject="mapped"
        )
        self.assertTrue(token_data["token"])
        identity.refresh_from_db()
        self.assertIsNotNone(identity.last_login_at)

        off_config = PortalSSOConfig(
            enabled=True,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            allowed_targets=self.config.allowed_targets,
            auto_provision=False,
        )
        unbound_ticket = self._issue(
            config=off_config,
            body={"external_user_id": "unbound-ext", "target": "/opportunity"},
            nonce="nonce-unbound-0123456789",
        )
        with self.assertRaises(PortalSSOServiceError) as bind_required:
            exchange_portal_ticket(
                unbound_ticket["ticket"], config=off_config, rate_limit_subject="unbound"
            )
        self.assertEqual(bind_required.exception.code, PortalSSOErrorCode.BIND_REQUIRED)

    def test_inactive_mapped_user_and_disabled_feature_are_rejected(self):
        inactive = User.objects.create(
            username="inactive-user",
            nick_name="Inactive User",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=False,
        )
        UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id="inactive-ext",
            user=inactive,
            status=UserExternalIdentity.Status.ACTIVE,
        )
        ticket = self._issue(
            body={"external_user_id": "inactive-ext", "target": "/opportunity"},
            nonce="nonce-inactive-0123456789",
        )
        with self.assertRaises(PortalSSOServiceError) as disabled:
            exchange_portal_ticket(ticket["ticket"], config=self.config, rate_limit_subject="inactive")
        self.assertEqual(disabled.exception.code, PortalSSOErrorCode.USER_DISABLED)

        off_config = PortalSSOConfig(
            enabled=False,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            allowed_targets=self.config.allowed_targets,
        )
        body, timestamp, nonce, signature = self._request(nonce="nonce-off-0123456789")
        with self.assertRaises(PortalSSOServiceError) as disabled_feature:
            create_portal_ticket(
                body,
                config=off_config,
                client_id=off_config.client_id,
                timestamp=timestamp,
                nonce=nonce,
                signature=signature,
                path=self.path,
                rate_limit_subject="off-feature",
            )
        self.assertEqual(disabled_feature.exception.code, PortalSSOErrorCode.DISABLED)

    def test_previous_secret_is_accepted_during_rotation(self):
        rotated = PortalSSOConfig(
            enabled=True,
            client_id=self.config.client_id,
            client_secret="new-secret",
            previous_client_secret="old-secret",
            allowed_targets=self.config.allowed_targets,
            auto_provision=False,
        )
        ticket = self._issue(
            config=rotated,
            signature_secret="old-secret",
            body={"external_user_id": "rotation-ext", "target": "/opportunity"},
            nonce="nonce-rotation-0123456789",
        )
        self.assertTrue(ticket["ticket"])

    @patch("common.utils.logger.maxkb_logger.info")
    def test_audit_log_contains_hashes_but_no_sensitive_values(self, info):
        body, _timestamp, _nonce, signature = self._request(nonce="nonce-audit-0123456789")
        self._issue(cache_backend=RecordingCache(), nonce="nonce-audit-0123456789")
        rendered = " ".join(str(part) for call in info.call_args_list for part in call.args)
        self.assertNotIn(self.config.client_secret, rendered)
        self.assertNotIn(signature, rendered)
        self.assertNotIn(body["external_user_id"], rendered)
        self.assertNotIn("ticket=", rendered)

    def test_existing_identity_disabled_and_conflicts_do_not_auto_bind(self):
        existing = User.objects.create(
            username="existing",
            nick_name="Existing",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id="disabled-user",
            user=existing,
            status=UserExternalIdentity.Status.DISABLED,
        )
        ticket = self._issue(
            body={"external_user_id": "disabled-user", "target": "/opportunity"},
            nonce="nonce-disabled-0123456789",
        )
        with self.assertRaises(PortalSSOServiceError) as disabled:
            exchange_portal_ticket(ticket["ticket"], config=self.config, rate_limit_subject="disabled")
        self.assertEqual(disabled.exception.code, PortalSSOErrorCode.USER_DISABLED)

        User.objects.create(
            username="conflict-name",
            nick_name="Conflict",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        conflict_ticket = self._issue(
            body={
                "external_user_id": "new-user",
                "username": "conflict-name",
                "display_name": "New",
                "target": "/opportunity",
            },
            nonce="nonce-conflict-0123456789",
        )
        with self.assertRaises(PortalSSOServiceError) as conflict:
            exchange_portal_ticket(conflict_ticket["ticket"], config=self.config, rate_limit_subject="conflict")
        self.assertEqual(conflict.exception.code, PortalSSOErrorCode.BIND_REQUIRED)

    def test_provider_and_user_constraints_protect_mapping(self):
        user = User.objects.create(
            username="constraint-user",
            nick_name="Constraint User",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        UserExternalIdentity.objects.create(provider="PORTAL", external_user_id="constraint-ext", user=user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserExternalIdentity.objects.create(
                    provider="PORTAL", external_user_id="constraint-ext", user=user,
                )
        with self.assertRaises(ProtectedError):
            user.delete()

    def test_external_identity_explicit_index_names_fit_django_limit(self):
        model_index_names = [index.name for index in UserExternalIdentity._meta.indexes]
        migration = importlib.import_module("users.migrations.0002_user_external_identity")
        migration_index_names = [
            operation.index.name
            for operation in migration.Migration.operations
            if hasattr(operation, "index")
        ]
        self.assertTrue(model_index_names)
        self.assertEqual(model_index_names, migration_index_names)
        self.assertTrue(all(len(name) <= 30 for name in model_index_names))
        self.assertTrue(all(len(name) <= 30 for name in migration_index_names))


class PortalSSOEndpointContractTests(TestCase):
    def setUp(self):
        self.config = PortalSSOConfig(
            enabled=True,
            client_id="bia-test",
            client_secret="portal-test-secret",
            allowed_targets=("/opportunity",),
        )

    @patch("users.views.portal_sso.exchange_portal_ticket")
    @patch("users.views.portal_sso._config")
    def test_exchange_sets_login_cookie_contract(self, get_config, exchange):
        from rest_framework.test import APIRequestFactory
        from users.views.portal_sso import PortalTicketExchangeView

        get_config.return_value = self.config
        exchange.return_value = ({"token": "formal-session-token", "target": "/opportunity"}, "file-token")
        request = APIRequestFactory().post("/admin/api/user/sso/portal/exchange", {"ticket": "A" * 43}, format="json")
        response = PortalTicketExchangeView.as_view()(request)
        cookie = response.cookies["mk_file_auth"]
        self.assertEqual(cookie.value, "file-token")
        self.assertEqual(cookie["path"], CONFIG.get_admin_path())
        self.assertEqual(int(cookie["max-age"]), 7 * 24 * 3600)
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        exchange.assert_called_once()

    @patch("users.views.portal_sso.create_portal_ticket")
    @patch("users.views.portal_sso._config")
    def test_tickets_endpoint_returns_opaque_ticket_not_formal_token(self, get_config, create):
        from rest_framework.test import APIRequestFactory
        from users.views.portal_sso import PortalTicketView

        get_config.return_value = self.config
        create.return_value = {
            "ticket": "A" * 43,
            "launch_path": "/admin/sso/portal#ticket=" + "A" * 43,
            "expires_in": 60,
            "request_id": "request-1",
        }
        request = APIRequestFactory().post(
            "/admin/api/user/sso/portal/tickets",
            {"external_user_id": "external-1", "target": "/opportunity"},
            HTTP_X_BIA_CLIENT_ID="bia-test",
            HTTP_X_BIA_TIMESTAMP=str(int(time.time() * 1000)),
            HTTP_X_BIA_NONCE="nonce-endpoint-0123456789",
            HTTP_X_BIA_SIGNATURE="signature",
            format="json",
        )
        response = PortalTicketView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("ticket", response.content.decode())
        self.assertNotIn("formal-session-token", response.content.decode())


class PortalSSOBindCommandTests(TestCase):
    def test_bind_command_is_idempotent_and_rejects_conflicting_owner(self):
        User.objects.create(
            username="bind-user",
            nick_name="Bind User",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        output = StringIO()
        call_command(
            "portal_sso_bind",
            provider="PORTAL",
            external_user_id="bind-ext",
            user_ref="bind-user",
            stdout=output,
        )
        call_command(
            "portal_sso_bind",
            provider="PORTAL",
            external_user_id="bind-ext",
            user_ref="bind-user",
            stdout=output,
        )
        self.assertEqual(UserExternalIdentity.objects.filter(provider="PORTAL", external_user_id="bind-ext").count(), 1)

        other = User.objects.create(
            username="bind-other",
            nick_name="Bind Other",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        with self.assertRaises(CommandError):
            call_command(
                "portal_sso_bind",
                provider="PORTAL",
                external_user_id="bind-ext",
                user_ref=str(other.id),
                stdout=StringIO(),
            )
        with self.assertRaises(CommandError):
            call_command(
                "portal_sso_bind",
                provider="PORTAL",
                external_user_id="missing-ext",
                user_ref="not-a-uuid-or-username",
                stdout=StringIO(),
            )
