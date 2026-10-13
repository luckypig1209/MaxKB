import importlib
import json
import threading
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
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from maxkb.const import CONFIG
from users.models import User
from users.models.external_identity import UserExternalIdentity
from users.services.portal_sso import (
    portal_display_name,
    PortalSSOConfig,
    PortalSSOErrorCode,
    PortalSSOServiceError,
    PortalSSOValidationError,
    canonical_json,
    create_legacy_portal_ticket,
    create_portal_ticket,
    exchange_portal_ticket,
    legacy_portal_signature,
    normalize_legacy_portal_payload,
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

    def test_portal_display_name_keeps_hash_out_of_the_label(self):
        long_name = "名" * 180
        nick = portal_display_name(long_name, "ext-long-display")
        self.assertLessEqual(len(nick), 150)
        self.assertTrue(nick.endswith("（门户）"))
        self.assertNotIn("portal_", nick)
        marked = portal_display_name("admin", "ext-mark", disambiguate=True)
        self.assertTrue(marked.startswith("admin（门户·"))
        self.assertEqual(len(marked.split("·", 1)[1].rstrip("）")), 6)
        empty = portal_display_name("   ", "ext-empty-display")
        self.assertTrue(empty.startswith("门户用户·"))
        self.assertEqual(len(empty.split("·", 1)[1]), 6)


class PortalSSOConfigTests(TestCase):
    def test_config_is_typed_and_defaults_do_not_contain_real_endpoints(self):
        config = PortalSSOConfig.from_mapping({})
        self.assertFalse(config.enabled)
        self.assertEqual(config.allowed_targets, ("/home", "/opportunity", "/opportunity/records"))
        self.assertEqual(config.client_secret, "")
        self.assertEqual(config.existing_user_policy, "REJECT")
        with self.assertRaises(PortalSSOValidationError):
            PortalSSOConfig.from_mapping({"PORTAL_SSO_EXISTING_USER_POLICY": "AUTO_BIND_BY_USERNAME"})

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

    def _policy_config(self, *, auto_provision=True, policy="CREATE_NAMESPACED"):
        return PortalSSOConfig(
            enabled=True,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            allowed_targets=self.config.allowed_targets,
            auto_provision=auto_provision,
            existing_user_policy=policy,
            ticket_ttl_seconds=60,
        )

    def _exchange_named(self, config, external_id, username, *, email=None, display_name=None, nonce=None):
        body = {
            "external_user_id": external_id,
            "username": username,
            "target": "/opportunity",
        }
        if email is not None:
            body["email"] = email
        if display_name is not None:
            body["display_name"] = display_name
        ticket = self._issue(
            config=config,
            body=body,
            nonce=nonce or f"nonce-{external_id}-0123456789",
        )
        return exchange_portal_ticket(
            ticket["ticket"], config=config, rate_limit_subject=external_id
        )

    def _assert_isolated_from(self, external_id, existing, *, portal_username):
        identity = UserExternalIdentity.objects.select_related("user").get(
            provider="PORTAL", external_user_id=external_id
        )
        self.assertNotEqual(identity.user_id, existing.id)
        self.assertEqual(identity.user.role, "USER")
        self.assertEqual(identity.user.source, "PORTAL")
        self.assertTrue(identity.user.username.startswith("portal_"))
        self.assertEqual(identity.user.nick_name, f"{portal_username}（门户）")
        self.assertNotIn(identity.user.username, identity.user.nick_name)
        self.assertEqual(identity.user.phone, "")
        self.assertIsNone(identity.user.email)
        self.assertEqual(identity.external_username, portal_username)
        self.assertFalse(
            UserExternalIdentity.objects.filter(provider="PORTAL", user=existing, external_user_id=external_id).exists()
        )
        return identity

    def test_same_name_conflict_never_binds_admin_user_or_workspace_admin(self):
        admin = User.objects.get(username="admin")
        ordinary = User.objects.create(
            username="ordinary-local",
            nick_name="Ordinary Local",
            email="ordinary-local@example.test",
            phone="13900001111",
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        workspace_admin = User.objects.create(
            username="workspace-admin",
            nick_name="Workspace Admin",
            email=None,
            phone="13900002222",
            password="!",
            role="WORKSPACE_MANAGE",
            source="LOCAL",
            is_active=True,
        )
        config = self._policy_config()
        self._exchange_named(config, "ext-admin", "admin", nonce="nonce-ext-admin-0123456789")
        self._exchange_named(
            config,
            "ext-ordinary",
            "ordinary-local",
            email="ordinary-local@example.test",
            nonce="nonce-ext-ordinary-01234567",
        )
        self._exchange_named(config, "ext-workspace", "workspace-admin", nonce="nonce-ext-workspace-012345")
        self._assert_isolated_from("ext-admin", admin, portal_username="admin")
        isolated = self._assert_isolated_from("ext-ordinary", ordinary, portal_username="ordinary-local")
        self.assertNotEqual(isolated.user.email, ordinary.email)
        self.assertNotEqual(isolated.user.phone, ordinary.phone)
        self.assertEqual(ordinary.phone, "13900001111")
        self._assert_isolated_from("ext-workspace", workspace_admin, portal_username="workspace-admin")

    def test_reject_policy_keeps_same_name_unbound(self):
        User.objects.create(
            username="reject-local",
            nick_name="Reject Local",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        config = self._policy_config(policy="REJECT")
        before = User.objects.count()
        with self.assertRaises(PortalSSOServiceError) as conflict:
            self._exchange_named(config, "ext-reject", "reject-local", nonce="nonce-ext-reject-012345678")
        self.assertEqual(conflict.exception.code, PortalSSOErrorCode.BIND_REQUIRED)
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(UserExternalIdentity.objects.filter(external_user_id="ext-reject").exists())

    def test_explicit_mapping_still_logs_into_the_bound_user(self):
        bound = User.objects.create(
            username="explicit-bound",
            nick_name="Explicit Bound",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        other = User.objects.create(
            username="explicit-other",
            nick_name="Explicit Other",
            email=None,
            password="!",
            role="ADMIN",
            source="LOCAL",
            is_active=True,
        )
        UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id="ext-explicit",
            user=bound,
            status=UserExternalIdentity.Status.ACTIVE,
        )
        token_data, _file_token = self._exchange_named(
            self._policy_config(),
            "ext-explicit",
            "explicit-other",
            nonce="nonce-ext-explicit-0123456",
        )
        self.assertEqual(TokenDetails(token_data["token"]).get_token_details()["id"], str(bound.id))
        self.assertFalse(UserExternalIdentity.objects.filter(user=other).exists())

    def test_auto_provision_off_creates_nothing_for_either_policy(self):
        before = User.objects.count()
        for policy in ("REJECT", "CREATE_NAMESPACED"):
            config = self._policy_config(auto_provision=False, policy=policy)
            with self.assertRaises(PortalSSOServiceError) as unbound:
                self._exchange_named(
                    config,
                    f"ext-off-{policy.lower()}",
                    f"brand-new-{policy.lower()}",
                    nonce=f"nonce-off-{policy.lower()}-012345",
                )
            self.assertEqual(unbound.exception.code, PortalSSOErrorCode.BIND_REQUIRED)
        self.assertEqual(User.objects.count(), before)

    def test_integrity_error_reuses_only_the_same_external_identity(self):
        config = self._policy_config()
        winner = User.objects.create(
            username="race-winner",
            nick_name="Race Winner",
            email=None,
            password="!",
            role="USER",
            source="PORTAL",
            is_active=True,
        )
        UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id="ext-race",
            user=winner,
            status=UserExternalIdentity.Status.ACTIVE,
        )
        original_filter = UserExternalIdentity.objects.filter
        state = {"calls": 0}

        def hide_first_identity(*args, **kwargs):
            state["calls"] += 1
            queryset = original_filter(*args, **kwargs)
            if state["calls"] == 1:
                return queryset.none()
            return queryset

        before = User.objects.count()
        with patch.object(UserExternalIdentity.objects, "filter", hide_first_identity), patch.object(
            User.objects, "create", side_effect=IntegrityError("duplicate")
        ):
            token_data, _file_token = self._exchange_named(
                config, "ext-race", "race-winner", nonce="nonce-ext-race-0123456789"
            )
        self.assertEqual(TokenDetails(token_data["token"]).get_token_details()["id"], str(winner.id))
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(UserExternalIdentity.objects.filter(external_user_id="ext-race").count(), 1)

        with patch.object(User.objects, "create", side_effect=IntegrityError("duplicate")):
            with self.assertRaises(PortalSSOServiceError) as unbound:
                self._exchange_named(
                    config, "ext-race-miss", "brand-new-race", nonce="nonce-ext-race-miss-012345"
                )
        self.assertEqual(unbound.exception.code, PortalSSOErrorCode.BIND_REQUIRED)
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(UserExternalIdentity.objects.filter(external_user_id="ext-race-miss").exists())

    def test_bound_local_user_is_not_rebound_to_another_portal_identity(self):
        owner = User.objects.create(
            username="owned-name",
            nick_name="Owned Name",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id="ext-owner",
            user=owner,
            status=UserExternalIdentity.Status.ACTIVE,
        )
        self._exchange_named(
            self._policy_config(),
            "ext-intruder",
            "owned-name",
            nonce="nonce-ext-intruder-01234567",
        )
        owner_identity = UserExternalIdentity.objects.get(external_user_id="ext-owner")
        intruder_identity = UserExternalIdentity.objects.get(external_user_id="ext-intruder")
        self.assertEqual(owner_identity.user_id, owner.id)
        self.assertNotEqual(intruder_identity.user_id, owner.id)
        self.assertEqual(intruder_identity.user.role, "USER")

    def test_legacy_username_tamper_cannot_capture_local_admin(self):
        admin = User.objects.get(username="admin")
        config = self._policy_config()
        timestamp = str(int(time.time() * 1000))
        signature = legacy_portal_signature(config.client_secret, config.client_id, timestamp)
        tampered = {
            "mobile": "13800000000",
            "username": "admin",
            "password": "not-a-credential",
            "signature": signature,
            "timestamp": int(timestamp),
        }
        ticket = create_legacy_portal_ticket(
            tampered,
            config=config,
            request_id="legacy-tamper",
            rate_limit_subject="legacy-tamper",
        )
        token_data, _file_token = exchange_portal_ticket(
            ticket["ticket"], config=config, rate_limit_subject="legacy-tamper-exchange"
        )
        identity = self._assert_isolated_from("admin", admin, portal_username="admin")
        self.assertEqual(TokenDetails(token_data["token"]).get_token_details()["id"], str(identity.user_id))
        self.assertNotEqual(identity.user_id, admin.id)

    @patch("common.utils.logger.maxkb_logger.info")
    def test_namespaced_provision_audit_omits_sensitive_values(self, info):
        self._exchange_named(
            self._policy_config(),
            "ext-audit",
            "admin",
            email="audit-secret@example.test",
            nonce="nonce-ext-audit-0123456789",
        )
        rendered = " ".join(str(part) for call in info.call_args_list for part in call.args)
        self.assertIn("CREATE_NAMESPACED", rendered)
        self.assertIn("created_namespaced", rendered)
        self.assertNotIn("admin", rendered)
        self.assertNotIn("audit-secret@example.test", rendered)
        self.assertNotIn(self.config.client_secret, rendered)
        self.assertNotIn("not-a-credential", rendered)
        self.assertNotIn("ticket=", rendered)

    def test_empty_portal_username_uses_portal_user_label(self):
        self._exchange_named(
            self._policy_config(),
            "ext-empty-name",
            "",
            nonce="nonce-ext-empty-name-01",
        )
        identity = UserExternalIdentity.objects.get(provider="PORTAL", external_user_id="ext-empty-name")
        self.assertTrue(identity.user.username.startswith("portal_"))
        self.assertTrue(identity.user.nick_name.startswith("门户用户·"))
        self.assertEqual(len(identity.user.nick_name.split("·", 1)[1]), 6)
        self.assertNotIn(identity.user.username, identity.user.nick_name)

    def test_namespaced_nick_uses_digest_when_friendly_name_is_taken(self):
        User.objects.create(
            username="friendly-nick-holder",
            nick_name="admin（门户）",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        admin = User.objects.get(username="admin")
        self._exchange_named(
            self._policy_config(),
            "ext-nick-clash",
            "admin",
            nonce="nonce-ext-nick-clash-01",
        )
        identity = UserExternalIdentity.objects.get(provider="PORTAL", external_user_id="ext-nick-clash")
        self.assertNotEqual(identity.user_id, admin.id)
        self.assertTrue(identity.user.username.startswith("portal_"))
        self.assertIn("（门户·", identity.user.nick_name)
        self.assertNotIn(identity.user.username, identity.user.nick_name)
        self.assertFalse(UserExternalIdentity.objects.filter(provider="PORTAL", user=admin).exists())

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



    def _explicit_admin(self):
        return User.objects.create(
            username="explicit-admin",
            nick_name="Explicit Admin",
            email=None,
            password="!",
            role="ADMIN",
            source="LOCAL",
            is_active=True,
        )

    def _isolated_identity(self, admin, external_id="explicit-ext"):
        isolated = User.objects.create(
            username="portal_" + "ef" * 24,
            nick_name="Explicit Isolated",
            email=None,
            password="!",
            role="USER",
            source="PORTAL",
            is_active=True,
        )
        identity = UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id=external_id,
            external_username="name-secret-do-not-print",
            display_name="display-secret-do-not-print",
            user=isolated,
            status=UserExternalIdentity.Status.ACTIVE,
            meta={"ticket": "ticket-secret-do-not-print"},
        )
        call_command(
            "portal_sso_rebind",
            provider="PORTAL",
            external_user_id=external_id,
            from_user=str(isolated.id),
            to_user=str(admin.id),
            apply=True,
            disable_source_user=True,
            allow_privileged_target=True,
            confirm_target_user_id=str(admin.id),
            stdout=StringIO(),
        )
        isolated.refresh_from_db()
        identity.refresh_from_db()
        return isolated, identity

    def test_explicit_admin_mapping_reuses_the_same_account(self):
        admin = self._explicit_admin()
        isolated, identity = self._isolated_identity(admin)
        config = self._policy_config()
        users_before = User.objects.count()
        identities_before = UserExternalIdentity.objects.count()

        token_data, _file_token = self._exchange_named(
            config, "explicit-ext", "name-secret-do-not-print", nonce="nonce-explicit-ext-0001"
        )
        self.assertEqual(TokenDetails(token_data["token"]).get_token_details()["id"], str(admin.id))
        token_data, _file_token = self._exchange_named(
            config, "explicit-ext", "renamed-portal-person", nonce="nonce-explicit-ext-0002"
        )
        self.assertEqual(TokenDetails(token_data["token"]).get_token_details()["id"], str(admin.id))
        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(UserExternalIdentity.objects.count(), identities_before)
        identity.refresh_from_db()
        self.assertEqual(identity.user_id, admin.id)
        self.assertEqual(UserExternalIdentity.objects.filter(provider="PORTAL", user=admin).count(), 1)
        isolated.refresh_from_db()
        self.assertFalse(isolated.is_active)
        self.assertTrue(User.objects.filter(id=isolated.id).exists())

    def test_unmapped_admin_name_stays_isolated_and_reject_creates_nothing(self):
        admin = self._explicit_admin()
        config = self._policy_config()
        before = User.objects.count()
        self._exchange_named(config, "explicit-admin", "explicit-admin", nonce="nonce-explicit-admin-001")
        identity = UserExternalIdentity.objects.get(provider="PORTAL", external_user_id="explicit-admin")
        self.assertNotEqual(identity.user_id, admin.id)
        self.assertEqual(identity.user.role, "USER")
        self.assertEqual(identity.user.source, "PORTAL")
        self.assertTrue(identity.user.username.startswith("portal_"))
        self.assertGreater(User.objects.count(), before)

        reject = self._policy_config(policy="REJECT")
        users_before = User.objects.count()
        with self.assertRaises(PortalSSOServiceError) as caught:
            self._exchange_named(reject, "reject-admin-ext", "explicit-admin", nonce="nonce-reject-admin-0001")
        self.assertEqual(caught.exception.code, PortalSSOErrorCode.BIND_REQUIRED)
        self.assertEqual(User.objects.count(), users_before)
        self.assertFalse(
            UserExternalIdentity.objects.filter(provider="PORTAL", external_user_id="reject-admin-ext").exists()
        )

    def test_ordinary_same_name_does_not_take_over_local_user(self):
        local = User.objects.create(
            username="ordinary-explicit",
            nick_name="Ordinary Explicit",
            email="ordinary-explicit@example.test",
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        self._exchange_named(
            self._policy_config(), "ordinary-explicit", "ordinary-explicit", nonce="nonce-ordinary-explicit-1"
        )
        identity = UserExternalIdentity.objects.get(provider="PORTAL", external_user_id="ordinary-explicit")
        self.assertNotEqual(identity.user_id, local.id)
        self.assertEqual(identity.user.role, "USER")
        self.assertEqual(identity.user.source, "PORTAL")

    def test_disabled_admin_rejects_portal_login(self):
        admin = self._explicit_admin()
        self._isolated_identity(admin)
        admin.is_active = False
        admin.save(update_fields=["is_active", "update_time"])
        with self.assertRaises(PortalSSOServiceError) as caught:
            self._exchange_named(self._policy_config(), "explicit-ext", "explicit-admin", nonce="nonce-disabled-admin-01")
        self.assertEqual(caught.exception.code, PortalSSOErrorCode.USER_DISABLED)

    def test_local_admin_password_login_survives_rebind(self):
        from users.serializers.login import LoginSerializer

        admin = self._explicit_admin()
        admin.set_password("LocalAdminSecret1")
        admin.save(update_fields=["password", "update_time"])
        password_hash = admin.password
        self._isolated_identity(admin)
        admin.refresh_from_db()
        self.assertEqual(admin.password, password_hash)
        self.assertEqual(admin.role, "ADMIN")
        self.assertEqual(admin.source, "LOCAL")
        token_data, _file_token = LoginSerializer.login(
            {"username": admin.username, "password": "LocalAdminSecret1"}
        )
        self.assertEqual(TokenDetails(token_data["token"]).get_token_details()["id"], str(admin.id))

    def test_rebound_admin_ticket_cannot_be_replayed(self):
        admin = self._explicit_admin()
        self._isolated_identity(admin)
        config = self._policy_config()
        ticket = self._issue(
            config=config,
            body={"external_user_id": "explicit-ext", "username": "explicit-admin", "target": "/opportunity"},
            nonce="nonce-replay-admin-0001",
        )
        exchange_portal_ticket(ticket["ticket"], config=config, rate_limit_subject="explicit-replay")
        with self.assertRaises(PortalSSOServiceError) as replay:
            exchange_portal_ticket(ticket["ticket"], config=config, rate_limit_subject="explicit-replay-2")
        self.assertEqual(replay.exception.code, PortalSSOErrorCode.TICKET_INVALID)

    @patch("common.utils.logger.maxkb_logger.info")
    def test_privileged_reuse_audit_omits_raw_identity(self, info):
        admin = self._explicit_admin()
        self._isolated_identity(admin)
        self._exchange_named(
            self._policy_config(), "explicit-ext", "name-secret-do-not-print", nonce="nonce-audit-admin-00001"
        )
        logged = " ".join(str(part) for call in info.call_args_list for part in call.args)
        self.assertIn("reused_explicit_privileged_mapping", logged)
        self.assertIn(str(admin.id), logged)
        self.assertNotIn("name-secret-do-not-print", logged)
        self.assertNotIn("display-secret-do-not-print", logged)
        self.assertNotIn("ticket-secret-do-not-print", logged)
        self.assertNotIn("LocalAdminSecret1", logged)

    def test_rebound_admin_sees_owned_knowledge_and_isolated_user_does_not(self):
        from knowledge.models.knowledge import Knowledge, KnowledgeFolder
        from knowledge.serializers.knowledge import KnowledgeSerializer

        admin = self._explicit_admin()
        isolated, _identity = self._isolated_identity(admin)
        workspace_id = "rebind-kb"
        folder = KnowledgeFolder.objects.create(id=workspace_id, name="管理员资料", workspace_id=workspace_id)
        knowledge = Knowledge.objects.create(
            name="管理员知识库",
            desc="",
            workspace_id=workspace_id,
            folder=folder,
            user=admin,
        )
        admin_rows = KnowledgeSerializer.Query(
            data={"workspace_id": workspace_id, "folder_id": workspace_id, "scope": "WORKSPACE", "user_id": admin.id}
        ).list()
        isolated_rows = KnowledgeSerializer.Query(
            data={
                "workspace_id": workspace_id,
                "folder_id": workspace_id,
                "scope": "WORKSPACE",
                "user_id": isolated.id,
            }
        ).list()
        admin_dump = json.dumps(admin_rows, default=str)
        isolated_dump = json.dumps(isolated_rows, default=str)
        self.assertIn(str(knowledge.id), admin_dump)
        self.assertNotIn(str(knowledge.id), isolated_dump)
        knowledge.refresh_from_db()
        self.assertEqual(knowledge.user_id, admin.id)


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

    def _legacy_body(self, username="portal-user"):
        timestamp = int(time.time() * 1000)
        return {
            "mobile": "13800000000",
            "username": username,
            "password": "not-a-credential",
            "signature": legacy_portal_signature(
                self.config.client_secret, self.config.client_id, str(timestamp)
            ),
            "timestamp": timestamp,
        }

    def test_legacy_mapping_subclass_is_copied_before_ticket_creation(self):
        source = type("PortalBody", (dict,), {})(self._legacy_body())
        payload = normalize_legacy_portal_payload(source)
        self.assertEqual(type(payload), dict)
        self.assertIsNot(payload, source)
        self.assertEqual(payload["username"], source["username"])
        self.assertIsNone(normalize_legacy_portal_payload({**source, "clientId": "extra"}))

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "portal-sso-legacy",
            }
        }
    )
    @patch("users.services.portal_sso.canonical_json", side_effect=AssertionError("legacy path"))
    @patch("users.views.portal_sso._config")
    def test_form_parsed_portal_json_issues_ticket_through_django_cache(self, get_config, _canonical):
        from django.core.cache import cache as django_cache
        from rest_framework.test import APIRequestFactory
        from users.views.portal_sso import PortalTicketView

        django_cache.clear()
        get_config.return_value = self.config
        body = self._legacy_body()
        request = APIRequestFactory().post(
            "/admin/api/user/sso/portal/tickets",
            data=json.dumps(body).encode(),
            content_type="application/x-www-form-urlencoded",
        )
        response = PortalTicketView.as_view()(request)
        rendered = response.content.decode()
        payload = json.loads(rendered)
        self.assertEqual(payload["code"], 200)
        ticket = payload["data"]["ticket"]
        self.assertGreaterEqual(len(ticket), 43)
        self.assertNotIn("not-a-credential", rendered)
        self.assertNotIn("dictionary update", rendered)
        self.assertNotIn("${token}", rendered)

        with self.assertRaises(PortalSSOServiceError) as unbound:
            exchange_portal_ticket(ticket, config=self.config, rate_limit_subject="legacy-unbound")
        self.assertEqual(unbound.exception.code, PortalSSOErrorCode.BIND_REQUIRED)

        issuing = PortalSSOConfig(
            enabled=True,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            allowed_targets=("/opportunity",),
            auto_provision=True,
        )
        get_config.return_value = issuing
        second = self._legacy_body(username="portal-user-exchange")
        second_request = APIRequestFactory().post(
            "/admin/api/user/sso/portal/tickets",
            data=json.dumps(second).encode(),
            content_type="application/x-www-form-urlencoded",
        )
        second_response = json.loads(PortalTicketView.as_view()(second_request).content.decode())
        session_ticket = second_response["data"]["ticket"]
        exchanged, _file_token = exchange_portal_ticket(
            session_ticket, config=issuing, rate_limit_subject="legacy-exchange"
        )
        self.assertTrue(exchanged["token"])
        self.assertEqual(exchanged["target"], "/opportunity")
        with self.assertRaises(PortalSSOServiceError) as replayed:
            exchange_portal_ticket(session_ticket, config=issuing, rate_limit_subject="legacy-replay")
        self.assertEqual(replayed.exception.code, PortalSSOErrorCode.TICKET_INVALID)

    @patch("users.views.portal_sso._config")
    def test_unknown_portal_body_does_not_leak_serializer_internals(self, get_config):
        from rest_framework.test import APIRequestFactory
        from users.views.portal_sso import PortalTicketView

        get_config.return_value = self.config
        request = APIRequestFactory().post(
            "/admin/api/user/sso/portal/tickets",
            {"mobile": "13800000000", "clientId": "extra"},
            format="json",
        )
        rendered = PortalTicketView.as_view()(request).content.decode()
        payload = json.loads(rendered)
        self.assertEqual(payload["code"], PortalSSOErrorCode.INVALID_REQUEST)
        self.assertNotIn("dictionary update", rendered)
        self.assertNotIn("unknown portal", rendered)

    @patch("django.core.cache.cache.add", side_effect=RuntimeError("redis-down-marker"))
    @patch("users.views.portal_sso._config")
    def test_cache_outage_hides_the_internal_exception(self, get_config, _add):
        from rest_framework.test import APIRequestFactory
        from users.views.portal_sso import PortalTicketView

        get_config.return_value = self.config
        request = APIRequestFactory().post(
            "/admin/api/user/sso/portal/tickets",
            self._legacy_body(),
            format="json",
        )
        rendered = PortalTicketView.as_view()(request).content.decode()
        payload = json.loads(rendered)
        self.assertEqual(payload["code"], PortalSSOErrorCode.UNAVAILABLE)
        self.assertNotIn("redis-down-marker", rendered)
        self.assertNotIn("Traceback", rendered)

    def _post_portal_body(self, body, *, content_type="application/json"):
        from rest_framework.test import APIRequestFactory
        from users.views.portal_sso import PortalTicketView

        if content_type == "application/json":
            request = APIRequestFactory().post(
                "/admin/api/user/sso/portal/tickets",
                body,
                format="json",
            )
        else:
            request = APIRequestFactory().post(
                "/admin/api/user/sso/portal/tickets",
                data=json.dumps(body).encode(),
                content_type=content_type,
            )
        rendered = PortalTicketView.as_view()(request).content.decode()
        return json.loads(rendered), rendered

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "portal-sso-live-body",
            }
        }
    )
    @patch("users.views.portal_sso.create_portal_ticket", side_effect=AssertionError("v2 path"))
    @patch("users.views.portal_sso._config")
    def test_live_portal_body_issues_ticket_and_ignores_extra_fields(self, get_config, _v2):
        from django.core.cache import cache as django_cache

        django_cache.clear()
        get_config.return_value = self.config
        body = self._legacy_body(username="admin")
        body["mobile"] = None
        body["autoCreate"] = False
        body["userId"] = "portal-user-id-secret"
        subclass = type("PortalBody", (dict,), {})(body)
        from users.services.portal_sso import classify_legacy_mapping

        protocol, classified, reason, _meta = classify_legacy_mapping(subclass)
        self.assertEqual(protocol, "legacy")
        self.assertEqual(reason, "legacy_recognized")
        self.assertEqual(type(classified), dict)
        self.assertNotIn("userId", classified)
        self.assertNotIn("autoCreate", classified)
        payload, rendered = self._post_portal_body(body)
        self.assertEqual(payload["code"], 200)
        self.assertGreaterEqual(len(payload["data"]["ticket"]), 43)
        self.assertNotIn("portal-user-id-secret", rendered)
        self.assertNotIn("not-a-credential", rendered)
        self.assertNotIn(body["signature"], rendered)
        self.assertNotIn("autoCreate", rendered)
        self.assertNotIn("dictionary update", rendered)

        form_body = self._legacy_body(username="admin-form")
        form_body["autoCreate"] = True
        form_body["userId"] = 10001
        form_payload, form_rendered = self._post_portal_body(
            form_body, content_type="application/x-www-form-urlencoded"
        )
        self.assertEqual(form_payload["code"], 200)
        self.assertGreaterEqual(len(form_payload["data"]["ticket"]), 43)
        self.assertNotIn("not-a-credential", form_rendered)

        same_signature = dict(form_body)
        replay_payload, _replay_rendered = self._post_portal_body(same_signature)
        self.assertEqual(replay_payload["code"], PortalSSOErrorCode.NONCE_REPLAY)

    @patch("users.views.portal_sso.create_portal_ticket", side_effect=AssertionError("v2 path"))
    @patch("users.views.portal_sso._config")
    def test_legacy_attempt_does_not_fall_through_when_fields_are_wrong(self, get_config, _v2):
        get_config.return_value = self.config
        missing, _rendered = self._post_portal_body(
            {"mobile": "", "password": "not-a-credential", "signature": "abc", "timestamp": 1}
        )
        self.assertEqual(missing["code"], PortalSSOErrorCode.INVALID_REQUEST)
        unknown = self._legacy_body()
        unknown["clientId"] = "extra"
        unknown_payload, unknown_rendered = self._post_portal_body(unknown)
        self.assertEqual(unknown_payload["code"], PortalSSOErrorCode.INVALID_REQUEST)
        self.assertNotIn("not-a-credential", unknown_rendered)
        self.assertNotIn(unknown["signature"], unknown_rendered)

        stale = self._legacy_body()
        stale["timestamp"] = 1
        stale["signature"] = legacy_portal_signature(self.config.client_secret, self.config.client_id, "1")
        stale_payload, _stale_rendered = self._post_portal_body(stale)
        self.assertEqual(stale_payload["code"], PortalSSOErrorCode.TIMESTAMP_INVALID)

        forged = self._legacy_body()
        forged["signature"] = "bm90LWEgc2lnbmF0dXJl"
        forged_payload, _forged_rendered = self._post_portal_body(forged)
        self.assertEqual(forged_payload["code"], PortalSSOErrorCode.INVALID_SIGNATURE)

    @patch("common.utils.logger.maxkb_logger.info")
    @patch("users.views.portal_sso._config")
    def test_legacy_classify_log_records_reason_without_sensitive_values(self, get_config, info):
        get_config.return_value = self.config
        body = self._legacy_body(username="admin")
        body["autoCreate"] = False
        body["userId"] = "portal-user-id-secret"
        body["clientId"] = "extra"
        _payload, rendered = self._post_portal_body(body)
        logged = " ".join(str(part) for call in info.call_args_list for part in call.args)
        self.assertIn("legacy_unknown_fields", logged)
        self.assertIn("has_username", logged)
        self.assertNotIn("admin", logged)
        self.assertNotIn("portal-user-id-secret", logged)
        self.assertNotIn("not-a-credential", logged)
        self.assertNotIn(body["signature"], logged)
        self.assertNotIn("not-a-credential", rendered)


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


class PortalSSORepairDisplayNameTests(TestCase):
    def _isolated(self, username, nick_name, external_username, external_id, source="PORTAL"):
        user = User.objects.create(
            username=username,
            nick_name=nick_name,
            email=None,
            password="!",
            role="USER",
            source=source,
            is_active=True,
        )
        if source == "PORTAL":
            UserExternalIdentity.objects.create(
                provider="PORTAL",
                external_user_id=external_id,
                external_username=external_username,
                user=user,
            )
        return user

    def test_repair_updates_only_hash_nicks_and_is_idempotent(self):
        isolated = self._isolated(
            "portal_" + "ab" * 24,
            "portal_" + "ab" * 24,
            "repair-portal-name",
            "repair-ext",
        )
        self._isolated(
            "portal_" + "cd" * 24,
            "already-friendly",
            "leave-me",
            "repair-friendly",
        )
        local = User.objects.create(
            username="portal_local_copy",
            nick_name="portal_local_copy",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        preview = StringIO()
        call_command("portal_sso_repair_display_names", stdout=preview)
        preview_text = preview.getvalue()
        self.assertIn("candidates=1", preview_text)
        self.assertIn(f"user_id={isolated.id}", preview_text)
        self.assertIn("updated=0", preview_text)
        self.assertNotIn("repair-portal-name", preview_text)
        self.assertNotIn("leave-me", preview_text)
        isolated.refresh_from_db()
        self.assertEqual(isolated.nick_name, isolated.username)

        applied = StringIO()
        call_command("portal_sso_repair_display_names", apply=True, stdout=applied)
        applied_text = applied.getvalue()
        self.assertIn("candidates=1", applied_text)
        self.assertIn("updated=1", applied_text)
        self.assertNotIn("repair-portal-name", applied_text)
        isolated.refresh_from_db()
        self.assertEqual(isolated.nick_name, "repair-portal-name（门户）")
        self.assertTrue(isolated.username.startswith("portal_"))
        local.refresh_from_db()
        self.assertEqual(local.nick_name, local.username)

        again = StringIO()
        call_command("portal_sso_repair_display_names", stdout=again)
        self.assertIn("candidates=0", again.getvalue())
        self.assertIn("updated=0", again.getvalue())


class PortalSSORebindCommandTests(TestCase):
    def _pair(
        self,
        suffix="ab",
        *,
        target_role="USER",
        target_source="LOCAL",
        source_role="USER",
        source_source="PORTAL",
        external_id="rebind-ext",
        target_username="rebind-target",
        target_nick="Rebind Target",
    ):
        source = User.objects.create(
            username="portal_" + (suffix * 24)[:48],
            nick_name=f"Isolated {suffix}",
            email=None,
            password="pw-secret-do-not-print",
            role=source_role,
            source=source_source,
            is_active=True,
        )
        target = User.objects.create(
            username=target_username,
            nick_name=target_nick,
            email=None,
            password="pw-secret-do-not-print",
            role=target_role,
            source=target_source,
            is_active=True,
        )
        identity = UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id=external_id,
            external_username="name-secret-do-not-print",
            display_name="display-secret-do-not-print",
            user=source,
            status=UserExternalIdentity.Status.ACTIVE,
            meta={"ticket": "ticket-secret-do-not-print", "signature": "signature-secret-do-not-print"},
        )
        return source, target, identity

    def _profile(self, user):
        user.refresh_from_db()
        return (user.username, user.nick_name, user.password, user.role, user.source, user.email, user.phone)

    def _command(self, source, target, external_id="rebind-ext", **overrides):
        options = {
            "provider": "PORTAL",
            "external_user_id": external_id,
            "from_user": str(source.id),
            "to_user": str(target.id),
        }
        options.update(overrides)
        output = StringIO()
        call_command("portal_sso_rebind", stdout=output, **options)
        return output.getvalue()

    def _assert_secret_free(self, text):
        self.assertNotIn("pw-secret-do-not-print", text)
        self.assertNotIn("name-secret-do-not-print", text)
        self.assertNotIn("display-secret-do-not-print", text)
        self.assertNotIn("ticket-secret-do-not-print", text)
        self.assertNotIn("signature-secret-do-not-print", text)
        self.assertNotIn("cookie-secret-do-not-print", text)

    def test_preview_does_not_write(self):
        source, target, identity = self._pair()
        before = self._profile(target)
        meta = dict(identity.meta)
        users_before = User.objects.count()
        text = self._command(source, target)
        self.assertIn("mode=preview", text)
        self.assertIn("outcome=ready", text)
        self.assertIn("mapping_updates=1", text)
        self.assertIn("users_created=0", text)
        self.assertIn("users_deleted=0", text)
        self.assertIn("target_profile_changed=false", text)
        self._assert_secret_free(text)
        identity.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(identity.user_id, source.id)
        self.assertEqual(identity.meta, meta)
        self.assertEqual(identity.external_username, "name-secret-do-not-print")
        self.assertTrue(source.is_active)
        self.assertEqual(self._profile(target), before)
        self.assertEqual(User.objects.count(), users_before)

    def test_flags_without_apply_do_not_write(self):
        source, target, identity = self._pair(target_role="ADMIN", target_username="rebind-admin", target_nick="Rebind Admin")
        text = self._command(
            source,
            target,
            disable_source_user=True,
            allow_privileged_target=True,
            confirm_target_user_id=str(target.id),
        )
        self.assertIn("mode=preview", text)
        self.assertIn("source_users_disabled=1", text)
        identity.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(identity.user_id, source.id)
        self.assertTrue(source.is_active)
        self.assertNotIn("last_rebind_from_user_id", identity.meta)

    def test_ordinary_rebind_disables_isolated_source_without_deleting_it(self):
        source, target, identity = self._pair()
        target_profile = self._profile(target)
        users_before = User.objects.count()
        text = self._command(source, target, apply=True, disable_source_user=True)
        self.assertIn("mode=apply", text)
        self.assertIn("outcome=applied", text)
        self.assertIn("mapping_updates=1", text)
        self.assertIn("source_users_disabled=1", text)
        self._assert_secret_free(text)
        identity.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(identity.user_id, target.id)
        self.assertEqual(identity.external_username, "name-secret-do-not-print")
        self.assertEqual(identity.display_name, "display-secret-do-not-print")
        self.assertEqual(identity.meta["last_rebind_from_user_id"], str(source.id))
        self.assertEqual(identity.meta["last_rebind_reason"], "portal_admin_explicit_binding")
        self.assertNotIn(source.username, identity.meta["last_rebind_from_user_id"])
        self.assertFalse(source.is_active)
        self.assertTrue(User.objects.filter(id=source.id).exists())
        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(self._profile(target), target_profile)

    def test_privileged_target_requires_exact_confirmation(self):
        source, target, identity = self._pair(
            target_role="ADMIN", target_username="rebind-admin", target_nick="Rebind Admin"
        )
        with self.assertRaises(CommandError):
            self._command(source, target, apply=True, disable_source_user=True, confirm_target_user_id=str(target.id))
        with self.assertRaises(CommandError):
            self._command(
                source,
                target,
                apply=True,
                disable_source_user=True,
                allow_privileged_target=True,
            )
        with self.assertRaises(CommandError):
            self._command(
                source,
                target,
                apply=True,
                disable_source_user=True,
                allow_privileged_target=True,
                confirm_target_user_id=target.username,
            )
        identity.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(identity.user_id, source.id)
        self.assertTrue(source.is_active)

    def test_confirmed_admin_rebind_is_idempotent(self):
        source, target, identity = self._pair(
            target_role="ADMIN", target_username="rebind-admin", target_nick="Rebind Admin"
        )
        kwargs = dict(
            apply=True,
            disable_source_user=True,
            allow_privileged_target=True,
            confirm_target_user_id=str(target.id),
        )
        self._command(source, target, **kwargs)
        identity.refresh_from_db()
        rebound_at = identity.meta["last_rebind_at"]
        users_before = User.objects.count()
        text = self._command(source, target, **kwargs)
        self.assertIn("outcome=idempotent", text)
        self.assertIn("mapping_updates=0", text)
        identity.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(identity.user_id, target.id)
        self.assertEqual(identity.meta["last_rebind_at"], rebound_at)
        self.assertFalse(source.is_active)
        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(UserExternalIdentity.objects.filter(provider="PORTAL").count(), 1)

    def test_from_user_mismatch_and_existing_target_mapping_fail(self):
        source, target, identity = self._pair()
        other = User.objects.create(
            username="rebind-other",
            nick_name="Rebind Other",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        with self.assertRaises(CommandError):
            self._command(other, target, apply=True, disable_source_user=True)
        occupied = User.objects.create(
            username="rebind-occupied",
            nick_name="Rebind Occupied",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id="occupied-ext",
            user=occupied,
            status=UserExternalIdentity.Status.ACTIVE,
        )
        with self.assertRaises(CommandError):
            self._command(source, occupied, apply=True, disable_source_user=True)
        identity.refresh_from_db()
        self.assertEqual(identity.user_id, source.id)

    def test_non_isolated_source_cannot_be_disabled(self):
        local, target, identity = self._pair(
            suffix="cd",
            source_source="LOCAL",
            target_username="rebind-local-target",
            target_nick="Rebind Local Target",
        )
        with self.assertRaises(CommandError):
            self._command(local, target, apply=True, disable_source_user=True)
        admin_source, admin_target, admin_identity = self._pair(
            suffix="gh",
            source_role="ADMIN",
            source_source="LOCAL",
            external_id="admin-source-ext",
            target_username="rebind-admin-target",
            target_nick="Rebind Admin Target",
        )
        with self.assertRaises(CommandError):
            self._command(admin_source, admin_target, external_id="admin-source-ext", apply=True, disable_source_user=True)
        identity.refresh_from_db()
        admin_identity.refresh_from_db()
        local.refresh_from_db()
        admin_source.refresh_from_db()
        self.assertEqual(identity.user_id, local.id)
        self.assertEqual(admin_identity.user_id, admin_source.id)
        self.assertTrue(local.is_active)
        self.assertTrue(admin_source.is_active)

    def test_failed_disable_rolls_back_the_owner_change(self):
        source, target, identity = self._pair(suffix="ij", external_id="rollback-ext", target_username="rollback-target", target_nick="Rollback Target")
        UserExternalIdentity.objects.create(
            provider="OTHER",
            external_user_id="other-ext",
            user=source,
            status=UserExternalIdentity.Status.ACTIVE,
        )
        with self.assertRaises(CommandError):
            self._command(source, target, external_id="rollback-ext", apply=True, disable_source_user=True)
        identity.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(identity.user_id, source.id)
        self.assertNotIn("last_rebind_from_user_id", identity.meta)
        self.assertTrue(source.is_active)

    def test_missing_mapping_is_not_created(self):
        source, target, _identity = self._pair(external_id="present-ext")
        before = UserExternalIdentity.objects.count()
        with self.assertRaises(CommandError):
            self._command(source, target, external_id="missing-ext", apply=True, disable_source_user=True)
        self.assertEqual(UserExternalIdentity.objects.count(), before)
        self.assertFalse(UserExternalIdentity.objects.filter(external_user_id="missing-ext").exists())

    def test_rollback_reenables_only_an_isolated_portal_user(self):
        source, target, identity = self._pair(suffix="kl", external_id="reverse-ext", target_username="reverse-target", target_nick="Reverse Target")
        target_profile = self._profile(target)
        self._command(source, target, external_id="reverse-ext", apply=True, disable_source_user=True)
        text = self._command(
            target,
            source,
            external_id="reverse-ext",
            apply=True,
            enable_target_user=True,
        )
        self.assertIn("outcome=applied", text)
        self.assertIn("target_users_enabled=1", text)
        identity.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(identity.user_id, source.id)
        self.assertTrue(source.is_active)
        self.assertEqual(identity.meta["last_rebind_from_user_id"], str(target.id))
        self.assertEqual(self._profile(target), target_profile)

        admin = User.objects.create(
            username="enable-admin",
            nick_name="Enable Admin",
            email=None,
            password="!",
            role="ADMIN",
            source="LOCAL",
            is_active=False,
        )
        with self.assertRaises(CommandError):
            self._command(
                source,
                admin,
                external_id="reverse-ext",
                apply=True,
                enable_target_user=True,
                allow_privileged_target=True,
                confirm_target_user_id=str(admin.id),
            )
        admin.refresh_from_db()
        identity.refresh_from_db()
        self.assertFalse(admin.is_active)
        self.assertEqual(identity.user_id, source.id)

    @patch("common.utils.logger.maxkb_logger.info")
    def test_apply_log_omits_secrets(self, info):
        source, target, _identity = self._pair(suffix="mn", external_id="id-secret-do-not-print", target_username="secret-target", target_nick="Secret Target")
        text = self._command(
            source,
            target,
            external_id="id-secret-do-not-print",
            apply=True,
            disable_source_user=True,
        )
        logged = " ".join(str(part) for call in info.call_args_list for part in call.args)
        self._assert_secret_free(text)
        self._assert_secret_free(logged)
        self.assertNotIn("id-secret-do-not-print", text)
        self.assertNotIn("id-secret-do-not-print", logged)
        self.assertIn("explicit_rebind", logged)
        self.assertIn(str(target.id), logged)


class PortalSSORebindConcurrencyTests(TransactionTestCase):
    """Commit so two threads can lock the same identity.

    Teardown deletes only the rows this test created. A full flush would remove
    the migrated default admin from the kept test database.
    """

    def _fixture_teardown(self):
        UserExternalIdentity.objects.filter(provider="PORTAL", external_user_id="concurrent-ext").delete()
        User.objects.filter(username__in=["portal_" + "zz" * 24, "concurrent-target"]).delete()

    def test_parallel_rebind_keeps_a_single_mapping(self):
        source = User.objects.create(
            username="portal_" + "zz" * 24,
            nick_name="Concurrent Isolated",
            email=None,
            password="!",
            role="USER",
            source="PORTAL",
            is_active=True,
        )
        target = User.objects.create(
            username="concurrent-target",
            nick_name="Concurrent Target",
            email=None,
            password="!",
            role="USER",
            source="LOCAL",
            is_active=True,
        )
        UserExternalIdentity.objects.create(
            provider="PORTAL",
            external_user_id="concurrent-ext",
            user=source,
            status=UserExternalIdentity.Status.ACTIVE,
            meta={},
        )
        connection.close()
        barrier = threading.Barrier(2)
        errors = []

        def run():
            try:
                barrier.wait(timeout=10)
                call_command(
                    "portal_sso_rebind",
                    provider="PORTAL",
                    external_user_id="concurrent-ext",
                    from_user=str(source.id),
                    to_user=str(target.id),
                    apply=True,
                    disable_source_user=True,
                    stdout=StringIO(),
                )
            except Exception as exc:  # noqa: BLE001 - the assertion below reports the thread failure.
                errors.append(exc)
            finally:
                connection.close()

        workers = [threading.Thread(target=run), threading.Thread(target=run)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        identity = UserExternalIdentity.objects.get(provider="PORTAL", external_user_id="concurrent-ext")
        self.assertEqual(UserExternalIdentity.objects.filter(provider="PORTAL", external_user_id="concurrent-ext").count(), 1)
        self.assertEqual(identity.user_id, target.id)
        source.refresh_from_db()
        self.assertFalse(source.is_active)
        self.assertTrue(User.objects.filter(id=source.id).exists())
