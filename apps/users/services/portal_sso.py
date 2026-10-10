"""Protocol primitives for the trusted portal SSO integration.

This module contains both the frozen wire-format primitives and the narrow
server-side ticket exchange used by the portal endpoints.  It does not expose
an HTTP endpoint or perform account administration; views and the management
command own those concerns.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

DEFAULT_ALLOWED_TARGETS = ("/home", "/opportunity", "/opportunity/records")

# The body is intentionally a closed schema.  Mapping/database work belongs
# to the ticket exchange phase, but rejecting unknown fields here ensures a
# field cannot be added without also being covered by the frozen signature.
PORTAL_SSO_FIELDS = frozenset(
    {
        "external_user_id",
        "username",
        "display_name",
        "email",
        "department_code",
        "target",
    }
)
PORTAL_SSO_REQUIRED_FIELDS = frozenset({"external_user_id"})
PORTAL_SSO_FIELD_MAX_LENGTHS = {
    "external_user_id": 256,
    "username": 150,
    "display_name": 150,
    "email": 254,
    "department_code": 64,
    "target": 512,
}


class PortalSSOValidationError(ValueError):
    """Raised when a portal request cannot satisfy the frozen SSO contract."""


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    raise PortalSSOValidationError("invalid portal SSO boolean configuration")


def _as_non_negative_int(value: Any, *, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise PortalSSOValidationError(f"invalid portal SSO {name}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PortalSSOValidationError(f"invalid portal SSO {name}") from exc
    if parsed < 0:
        raise PortalSSOValidationError(f"invalid portal SSO {name}")
    return parsed


def _mapping_value(mapping: Mapping[str, Any], name: str, default: Any = None) -> Any:
    """Read both Config keys and explicitly-prefixed environment-style keys."""

    base_name = name.removeprefix("PORTAL_SSO_")
    for key in (name, f"PORTAL_SSO_{base_name}", f"MAXKB_{name}", f"MAXKB_PORTAL_SSO_{base_name}"):
        if key in mapping:
            return mapping[key]
    return default


def _split_targets(value: Any) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_ALLOWED_TARGETS
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",") if item.strip()]
    else:
        try:
            values = [str(item) for item in value]
        except TypeError as exc:
            raise PortalSSOValidationError("invalid portal SSO allowed targets") from exc
    if not values:
        return ()
    normalized: list[str] = []
    for target in values:
        _validate_relative_target(target)
        if target not in normalized:
            normalized.append(target)
    return tuple(normalized)


@dataclass(frozen=True)
class PortalSSOConfig:
    """Typed, non-secret view of ``MAXKB_PORTAL_SSO_*`` configuration."""

    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    previous_client_secret: str = ""
    allowed_clock_skew_seconds: int = 60
    ticket_ttl_seconds: int = 60
    auto_provision: bool = False
    default_workspace: str = "default"
    portal_login_url: str = ""
    allowed_targets: tuple[str, ...] = DEFAULT_ALLOWED_TARGETS

    def __post_init__(self) -> None:
        if self.allowed_clock_skew_seconds < 0 or self.ticket_ttl_seconds < 0:
            raise PortalSSOValidationError("portal SSO time values must be non-negative")
        if self.enabled and self.ticket_ttl_seconds <= 0:
            raise PortalSSOValidationError("enabled portal SSO requires a positive ticket TTL")
        if self.enabled and not self.allowed_targets:
            raise PortalSSOValidationError("enabled portal SSO requires at least one allowed target")
        if not self.default_workspace or not isinstance(self.default_workspace, str):
            raise PortalSSOValidationError("portal SSO default workspace must be a non-empty string")
        # Validate configured targets even when callers instantiate the
        # dataclass directly instead of using ``from_mapping``.
        for target in self.allowed_targets:
            _validate_relative_target(target)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> PortalSSOConfig:
        if not isinstance(mapping, Mapping):
            raise PortalSSOValidationError("portal SSO configuration must be a mapping")
        return cls(
            enabled=_as_bool(_mapping_value(mapping, "PORTAL_SSO_ENABLED", False), default=False),
            client_id=str(_mapping_value(mapping, "PORTAL_SSO_CLIENT_ID", "") or ""),
            client_secret=str(_mapping_value(mapping, "PORTAL_SSO_CLIENT_SECRET", "") or ""),
            previous_client_secret=str(
                _mapping_value(mapping, "PORTAL_SSO_PREVIOUS_CLIENT_SECRET", "") or ""
            ),
            allowed_clock_skew_seconds=_as_non_negative_int(
                _mapping_value(mapping, "PORTAL_SSO_ALLOWED_CLOCK_SKEW_SECONDS", 60),
                default=60,
                name="allowed clock skew",
            ),
            ticket_ttl_seconds=_as_non_negative_int(
                _mapping_value(mapping, "PORTAL_SSO_TICKET_TTL_SECONDS", 60),
                default=60,
                name="ticket TTL",
            ),
            auto_provision=_as_bool(_mapping_value(mapping, "PORTAL_SSO_AUTO_PROVISION", False), default=False),
            default_workspace=str(_mapping_value(mapping, "PORTAL_SSO_DEFAULT_WORKSPACE", "default") or "default"),
            portal_login_url=str(_mapping_value(mapping, "PORTAL_SSO_PORTAL_LOGIN_URL", "") or ""),
            allowed_targets=_split_targets(_mapping_value(mapping, "PORTAL_SSO_ALLOWED_TARGETS", None)),
        )

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> PortalSSOConfig:
        """Compatibility alias for callers passing the MaxKB ``Config``."""

        return cls.from_mapping(config)

    def validate_enabled(self) -> PortalSSOConfig:
        """Validate required operational values when the integration is enabled."""

        if self.enabled and (not self.client_id or not self.client_secret):
            raise PortalSSOValidationError("enabled portal SSO requires client ID and client secret")
        if self.enabled and self.ticket_ttl_seconds <= 0:
            raise PortalSSOValidationError("enabled portal SSO requires a positive ticket TTL")
        if self.enabled and not self.allowed_targets:
            raise PortalSSOValidationError("enabled portal SSO requires at least one allowed target")
        return self


def canonical_json(value: Mapping[str, Any]) -> str:
    """Return the frozen compact UTF-8 JSON representation of an object.

    ``ensure_ascii=False`` is intentional: the resulting UTF-8 bytes are the
    signed representation, including Chinese and other non-ASCII values.
    ``allow_nan=False`` prevents different JSON implementations from treating
    NaN/Infinity inconsistently.
    """

    if not isinstance(value, Mapping):
        raise PortalSSOValidationError("portal SSO request body must be a JSON object")
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PortalSSOValidationError("portal SSO request body is not canonicalizable") from exc


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_json(value).encode("utf-8")


# Common names used by callers/readers of the protocol specification.
canonicalize_json = canonical_json
build_canonical_json = canonical_json


def _validate_component(
    value: Any,
    name: str,
    *,
    required: bool = True,
    max_length: int = 512,
    text_only: bool = False,
) -> str:
    if text_only and not isinstance(value, str):
        raise PortalSSOValidationError(f"invalid portal SSO {name}")
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise PortalSSOValidationError(f"invalid portal SSO {name}")
    text = str(value)
    if required and not text:
        raise PortalSSOValidationError(f"portal SSO {name} is required")
    if len(text) > max_length or any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise PortalSSOValidationError(f"invalid portal SSO {name}")
    return text


_METHOD_RE = re.compile(r"^[A-Z]+$")


def _validate_request_path(path: Any) -> str:
    path_text = _validate_component(path, "request path", max_length=2048, text_only=True)
    if not path_text.startswith("/") or path_text.startswith("//") or "\\" in path_text:
        raise PortalSSOValidationError("portal SSO request path must be relative")
    try:
        parsed = urlsplit(path_text)
    except ValueError as exc:
        raise PortalSSOValidationError("invalid portal SSO request path") from exc
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise PortalSSOValidationError("portal SSO request path must not contain a URL or query")
    if unquote(path_text) != path_text:
        raise PortalSSOValidationError("encoded portal SSO request paths are not allowed")
    return path_text


def _validate_relative_target(target: Any) -> str:
    target_text = _validate_component(target, "target", max_length=512, text_only=True)
    if not target_text.startswith("/") or target_text.startswith("//") or "\\" in target_text:
        raise PortalSSOValidationError("portal SSO target must be a relative path")
    try:
        parsed = urlsplit(target_text)
    except ValueError as exc:
        raise PortalSSOValidationError("invalid portal SSO target") from exc
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise PortalSSOValidationError("portal SSO target must be a relative path")
    # Reject encoded slash, backslash and dot-segment tricks even when a
    # future caller changes the matching strategy from exact to prefix-based.
    decoded = unquote(target_text)
    if decoded != target_text or "\\" in decoded or "/../" in decoded or "/./" in decoded:
        raise PortalSSOValidationError("encoded or ambiguous portal SSO target")
    if any(part == ".." for part in target_text.split("/")):
        raise PortalSSOValidationError("portal SSO target contains a parent segment")
    return target_text


def validate_portal_payload(
    payload: Mapping[str, Any],
    allowed_targets: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Validate and return a shallow copy of the closed portal identity body."""

    if not isinstance(payload, Mapping):
        raise PortalSSOValidationError("portal SSO request body must be a JSON object")
    unknown = set(payload) - PORTAL_SSO_FIELDS
    if unknown:
        raise PortalSSOValidationError("unknown portal SSO request field")
    missing = PORTAL_SSO_REQUIRED_FIELDS - set(payload)
    if missing:
        raise PortalSSOValidationError("missing required portal SSO request field")

    validated: dict[str, Any] = {}
    for field in PORTAL_SSO_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        max_length = PORTAL_SSO_FIELD_MAX_LENGTHS[field]
        if field == "external_user_id":
            if not isinstance(value, str) or not value.strip() or len(value) > max_length:
                raise PortalSSOValidationError("invalid portal SSO external user ID")
            if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
                raise PortalSSOValidationError("invalid portal SSO external user ID")
            validated[field] = value
        elif field == "target":
            target = _validate_relative_target(value)
            configured_targets = tuple(allowed_targets or DEFAULT_ALLOWED_TARGETS)
            configured_targets = tuple(_validate_relative_target(item) for item in configured_targets)
            if target not in configured_targets:
                raise PortalSSOValidationError("portal SSO target is not allowed")
            validated[field] = target
        else:
            if value is not None and not isinstance(value, str):
                raise PortalSSOValidationError(f"invalid portal SSO {field}")
            if isinstance(value, str) and (
                len(value) > max_length or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
            ):
                raise PortalSSOValidationError(f"invalid portal SSO {field}")
            validated[field] = value
    return validated


# Alias kept explicit for endpoint/serializer code in the next SSO phase.
validate_portal_request = validate_portal_payload
validate_request_fields = validate_portal_payload


def canonical_request(
    method: str,
    path: str,
    client_id: str,
    timestamp: str | int,
    nonce: str,
    body: Mapping[str, Any],
) -> str:
    """Build the exact newline-delimited request string covered by HMAC."""

    method_text = _validate_component(method, "method", max_length=16, text_only=True)
    if not _METHOD_RE.fullmatch(method_text):
        raise PortalSSOValidationError("portal SSO method must be an uppercase token")
    path_text = _validate_request_path(path)
    client_text = _validate_component(client_id, "client ID", max_length=256, text_only=True)
    timestamp_text = _validate_component(timestamp, "timestamp", max_length=32)
    if not timestamp_text.isdigit():
        raise PortalSSOValidationError("portal SSO timestamp must be an integer")
    nonce_text = _validate_component(nonce, "nonce", max_length=256, text_only=True)
    # A protocol validator cannot prove entropy, but it can reject identifiers
    # that are too short to carry the required 128 bits of randomness.
    if len(nonce_text.encode("utf-8")) < 16:
        raise PortalSSOValidationError("portal SSO nonce must contain at least 128 bits")
    body_hash = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return "\n".join(  # noqa: FLY002 - explicit fields make the signed wire format auditable.
        (method_text, path_text, client_text, timestamp_text, nonce_text, body_hash)
    )


build_canonical_request = canonical_request


def generate_signature(client_secret: str, canonical_request_text: str) -> str:
    """Generate the Base64 HMAC-SHA256 signature for canonical request text."""

    secret = _validate_component(client_secret, "client secret", max_length=4096, text_only=True)
    if not isinstance(canonical_request_text, str):
        raise PortalSSOValidationError("canonical request must be text")
    try:
        digest = hmac.new(secret.encode("utf-8"), canonical_request_text.encode("utf-8"), hashlib.sha256).digest()
    except UnicodeEncodeError as exc:
        raise PortalSSOValidationError("invalid portal SSO signature input") from exc
    return base64.b64encode(digest).decode("ascii")


generate_hmac_signature = generate_signature


def verify_signature(client_secret: str, canonical_request_text: str, signature: str | bytes) -> bool:
    """Constant-time verify of a strict Base64 HMAC-SHA256 signature.

    Invalid Base64 and malformed inputs return ``False`` without exposing the
    decoder exception or any secret material to callers.
    """

    try:
        if not isinstance(canonical_request_text, str):
            return False
        expected = hmac.new(
            _validate_component(client_secret, "client secret", max_length=4096, text_only=True).encode("utf-8"),
            canonical_request_text.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        if isinstance(signature, bytes):
            supplied_text = signature.decode("ascii")
        elif isinstance(signature, str):
            supplied_text = signature
        else:
            return False
        supplied = base64.b64decode(supplied_text.encode("ascii"), validate=True)
        return hmac.compare_digest(expected, supplied)
    except (UnicodeError, ValueError, TypeError, binascii.Error):
        return False


verify_hmac_signature = verify_signature


def sign_request(
    client_secret: str,
    method: str,
    path: str,
    client_id: str,
    timestamp: str | int,
    nonce: str,
    body: Mapping[str, Any],
) -> str:
    return generate_signature(client_secret, canonical_request(method, path, client_id, timestamp, nonce, body))


def verify_request_signature(
    client_secret: str,
    signature: str | bytes,
    method: str,
    path: str,
    client_id: str,
    timestamp: str | int,
    nonce: str,
    body: Mapping[str, Any],
) -> bool:
    try:
        request_text = canonical_request(method, path, client_id, timestamp, nonce, body)
    except (PortalSSOValidationError, TypeError, ValueError):
        return False
    return verify_signature(client_secret, request_text, signature)


def validate_timestamp(
    timestamp: str | int,
    *,
    now_ms: int | None = None,
    allowed_clock_skew_seconds: int = 60,
) -> bool:
    """Validate a Unix-millisecond timestamp against the configured window."""

    if isinstance(timestamp, bool) or (not isinstance(timestamp, (str, int))):
        raise PortalSSOValidationError("invalid portal SSO timestamp")
    timestamp_text = str(timestamp)
    if not timestamp_text.isdigit():
        raise PortalSSOValidationError("invalid portal SSO timestamp")
    timestamp_value = int(timestamp_text)
    if timestamp_value < 0:
        raise PortalSSOValidationError("invalid portal SSO timestamp")
    skew = _as_non_negative_int(allowed_clock_skew_seconds, default=60, name="allowed clock skew")
    current = int(time.time() * 1000) if now_ms is None else now_ms
    if isinstance(current, bool) or not isinstance(current, int) or current < 0:
        raise PortalSSOValidationError("invalid portal SSO current time")
    if abs(current - timestamp_value) > skew * 1000:
        raise PortalSSOValidationError("portal SSO timestamp is outside the allowed window")
    return True


validate_time_window = validate_timestamp


def is_timestamp_valid(timestamp: str | int, **kwargs: Any) -> bool:
    return _is_timestamp_valid(timestamp, **kwargs)


def _is_timestamp_valid(timestamp: str | int, **kwargs: Any) -> bool:
    try:
        return validate_timestamp(timestamp, **kwargs)
    except PortalSSOValidationError:
        return False


# ---------------------------------------------------------------------------
# SSO-02 stateful ticket exchange
# ---------------------------------------------------------------------------

class PortalSSOErrorCode:
    """Stable, non-enumerating business codes used by the two SSO endpoints."""

    DISABLED = "SSO_DISABLED"
    CONFIG_INVALID = "SSO_CONFIG_INVALID"
    INVALID_REQUEST = "SSO_INVALID_REQUEST"
    INVALID_SIGNATURE = "SSO_INVALID_SIGNATURE"
    TIMESTAMP_INVALID = "SSO_TIMESTAMP_INVALID"
    NONCE_REPLAY = "SSO_NONCE_REPLAY"
    TICKET_INVALID = "SSO_TICKET_INVALID"
    BIND_REQUIRED = "SSO_BIND_REQUIRED"
    USER_DISABLED = "SSO_USER_DISABLED"
    RATE_LIMITED = "SSO_RATE_LIMITED"
    UNAVAILABLE = "SSO_UNAVAILABLE"


class PortalSSOServiceError(Exception):
    """Service-layer error carrying a stable code and safe public message."""

    def __init__(self, code: str, message: str = "Portal SSO request failed", *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _cache_backend(cache_backend=None):
    if cache_backend is not None:
        return cache_backend
    from django.core.cache import cache

    return cache


def _cache_version():
    from common.constants.cache_version import Cache_Version

    return Cache_Version.SYSTEM.get_version()


def _digest_cache_key(prefix: str, value: str) -> str:
    return f"sso:portal:{prefix}:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _request_id(value: str | None = None) -> str:
    """Use only a bounded opaque correlation ID in logs/responses."""

    if isinstance(value, str) and 0 < len(value) <= 128 and re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        return value
    import uuid

    return uuid.uuid4().hex


def _external_id_digest(external_user_id: str | None) -> str | None:
    if not isinstance(external_user_id, str) or not external_user_id:
        return None
    return hashlib.sha256(external_user_id.encode("utf-8")).hexdigest()


def _audit(event: str, outcome: str, request_id: str, client_id: str | None = None,
           user_id: str | None = None, external_user_id: str | None = None) -> None:
    """Emit an audit event with no secret, ticket, token or raw identity data."""

    try:
        from common.utils.logger import maxkb_logger

        maxkb_logger.info(
            "portal_sso event=%s outcome=%s request_id=%s client_id=%s user_id=%s external_user_id_sha256=%s",
            event,
            outcome,
            request_id,
            client_id or "",
            user_id or "",
            _external_id_digest(external_user_id) or "",
        )
    except Exception:  # noqa: BLE001, S110 - audit failure must not break authentication.
        # Audit logging must never turn a successful login into an outage.
        pass


def _rate_limit(cache_backend, kind: str, subject: str, *, limit: int = 60, window_seconds: int = 60) -> bool:
    """A small cache-backed independent limiter for tickets and exchanges."""

    key = _digest_cache_key(f"rate:{kind}", subject)
    version = _cache_version()
    try:
        if cache_backend.add(key, 1, timeout=window_seconds, version=version):
            return True
        count = cache_backend.incr(key, 1, version=version)
        return int(count) <= limit
    except Exception as exc:
        raise PortalSSOServiceError(PortalSSOErrorCode.UNAVAILABLE) from exc


def _require_enabled(config: PortalSSOConfig) -> None:
    try:
        config.validate_enabled()
    except PortalSSOValidationError as exc:
        raise PortalSSOServiceError(PortalSSOErrorCode.CONFIG_INVALID) from exc
    if not config.enabled:
        raise PortalSSOServiceError(PortalSSOErrorCode.DISABLED)


def _verify_client_signature(
    config: PortalSSOConfig,
    *,
    client_id: str,
    timestamp: str | int,
    nonce: str,
    signature: str | bytes,
    method: str,
    path: str,
    body: Mapping[str, Any],
) -> bool:
    if not isinstance(client_id, str) or not isinstance(config.client_id, str):
        return False
    try:
        if not hmac.compare_digest(client_id.encode("utf-8"), config.client_id.encode("utf-8")):
            return False
    except (UnicodeError, TypeError):
        return False
    try:
        request_text = canonical_request(method, path, client_id, timestamp, nonce, body)
    except (PortalSSOValidationError, TypeError, ValueError):
        return False
    secrets_to_try = [config.client_secret]
    if config.previous_client_secret and config.previous_client_secret != config.client_secret:
        secrets_to_try.append(config.previous_client_secret)
    # Evaluate each key, rather than returning on the first match, to keep the
    # current/previous key rotation path from becoming a timing oracle.
    valid = False
    for secret in secrets_to_try:
        valid = verify_signature(secret, request_text, signature) or valid
    return valid


def _identity_payload_for_ticket(payload: Mapping[str, Any]) -> dict[str, Any]:
    # Do not retain arbitrary mapping subclasses or unknown extension fields.
    return {field: payload[field] for field in PORTAL_SSO_FIELDS if field in payload}


def create_portal_ticket(
    payload: Mapping[str, Any],
    *,
    config: PortalSSOConfig,
    client_id: str,
    timestamp: str | int,
    nonce: str,
    signature: str | bytes,
    path: str,
    request_id: str | None = None,
    rate_limit_subject: str = "unknown",
    cache_backend=None,
) -> dict[str, Any]:
    """Verify a signed portal request and persist a one-time ticket."""

    correlation_id = _request_id(request_id)
    backend = _cache_backend(cache_backend)
    _require_enabled(config)
    if not _rate_limit(backend, "tickets", rate_limit_subject):
        _audit("ticket", "rate_limited", correlation_id, client_id)
        raise PortalSSOServiceError(PortalSSOErrorCode.RATE_LIMITED)

    try:
        validated = validate_portal_payload(payload, config.allowed_targets)
    except PortalSSOValidationError as exc:
        _audit("ticket", "invalid_request", correlation_id, client_id)
        raise PortalSSOServiceError(PortalSSOErrorCode.INVALID_REQUEST) from exc

    try:
        validate_timestamp(timestamp, allowed_clock_skew_seconds=config.allowed_clock_skew_seconds)
    except PortalSSOValidationError as exc:
        _audit(
            "ticket",
            "timestamp_invalid",
            correlation_id,
            client_id,
            external_user_id=validated.get("external_user_id"),
        )
        raise PortalSSOServiceError(PortalSSOErrorCode.TIMESTAMP_INVALID) from exc

    if not _verify_client_signature(
        config,
        client_id=client_id,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
        method="POST",
        path=path,
        body=validated,
    ):
        _audit(
            "ticket",
            "invalid_signature",
            correlation_id,
            client_id,
            external_user_id=validated.get("external_user_id"),
        )
        # Keep stale timestamps and malformed signatures indistinguishable.
        raise PortalSSOServiceError(PortalSSOErrorCode.INVALID_SIGNATURE)

    nonce_value = str(nonce)
    if len(nonce_value.encode("utf-8")) < 16:
        _audit(
            "ticket",
            "invalid_nonce",
            correlation_id,
            client_id,
            external_user_id=validated.get("external_user_id"),
        )
        raise PortalSSOServiceError(PortalSSOErrorCode.NONCE_REPLAY)
    nonce_key = _digest_cache_key(f"nonce:{client_id}", nonce_value)
    nonce_ttl = max(120, config.allowed_clock_skew_seconds * 2)
    try:
        if not backend.add(nonce_key, 1, timeout=nonce_ttl, version=_cache_version()):
            _audit(
                "ticket",
                "nonce_replay",
                correlation_id,
                client_id,
                external_user_id=validated.get("external_user_id"),
            )
            raise PortalSSOServiceError(PortalSSOErrorCode.NONCE_REPLAY)
    except PortalSSOServiceError:
        raise
    except Exception as exc:
        raise PortalSSOServiceError(PortalSSOErrorCode.UNAVAILABLE) from exc

    import secrets
    import time as _time

    target = validated.get("target")
    if not target:
        target = "/opportunity" if "/opportunity" in config.allowed_targets else config.allowed_targets[0]
    ticket_record = {
        "client_id": config.client_id,
        "identity": _identity_payload_for_ticket(validated),
        "target": target,
        "request_id": correlation_id,
        "issued_at_ms": int(_time.time() * 1000),
    }
    ticket_ttl = config.ticket_ttl_seconds
    if ticket_ttl <= 0:
        raise PortalSSOServiceError(PortalSSOErrorCode.CONFIG_INVALID)

    ticket = ""
    ticket_key = ""
    for _ in range(3):
        ticket = secrets.token_urlsafe(32)  # 256 bits before URL-safe encoding.
        ticket_key = _digest_cache_key("ticket", ticket)
        try:
            if backend.add(ticket_key, ticket_record, timeout=ticket_ttl, version=_cache_version()):
                break
        except Exception as exc:
            raise PortalSSOServiceError(PortalSSOErrorCode.UNAVAILABLE) from exc
    else:
        raise PortalSSOServiceError(PortalSSOErrorCode.UNAVAILABLE)

    _audit("ticket", "issued", correlation_id, config.client_id, external_user_id=validated.get("external_user_id"))
    from maxkb.const import CONFIG

    launch_path = f"{CONFIG.get_admin_path().rstrip('/')}/sso/portal#ticket={ticket}"
    return {
        # The portal's current resultPath reads this opaque value directly.
        # It is still only a one-time ticket; no MaxKB session token is put in
        # the launch URL or returned from this endpoint.
        "ticket": ticket,
        "launch_path": launch_path,
        "expires_in": ticket_ttl,
        "request_id": correlation_id,
    }


def _safe_ticket_text(ticket: Any) -> str:
    if not isinstance(ticket, str) or len(ticket) < 43 or len(ticket) > 512:
        raise PortalSSOServiceError(PortalSSOErrorCode.TICKET_INVALID)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", ticket):
        raise PortalSSOServiceError(PortalSSOErrorCode.TICKET_INVALID)
    return ticket


def _resolve_portal_user(payload: Mapping[str, Any], config: PortalSSOConfig, *, provider: str = "PORTAL"):
    """Resolve an existing mapping or provision a minimum-role user."""

    import secrets

    from common.constants.permission_constants import RoleConstants
    from common.utils.common import password_encrypt
    from django.db import IntegrityError, transaction
    from django.db.models import Q
    from django.utils import timezone
    from users.models import User
    from users.models.external_identity import UserExternalIdentity

    external_id = payload["external_user_id"]
    identity = (
        UserExternalIdentity.objects.select_related("user")
        .filter(provider=provider, external_user_id=external_id)
        .first()
    )
    if identity is not None:
        try:
            user = identity.user
        except User.DoesNotExist as exc:
            raise PortalSSOServiceError(PortalSSOErrorCode.USER_DISABLED) from exc
        if identity.status != UserExternalIdentity.Status.ACTIVE or not user.is_active:
            raise PortalSSOServiceError(PortalSSOErrorCode.USER_DISABLED)
        identity.external_username = payload.get("username") or identity.external_username
        identity.display_name = payload.get("display_name") or identity.display_name
        identity.email = payload.get("email") or identity.email
        identity.department_code = payload.get("department_code") or identity.department_code
        identity.last_login_at = timezone.now()
        identity.save(
            update_fields=[
                "external_username",
                "display_name",
                "email",
                "department_code",
                "last_login_at",
                "update_time",
            ]
        )
        return user, identity

    if not config.auto_provision:
        raise PortalSSOServiceError(PortalSSOErrorCode.BIND_REQUIRED)

    username = (payload.get("username") or "").strip()
    email = payload.get("email") or None
    display_name = (payload.get("display_name") or "").strip()
    # Only explicit identity values can collide with a local account.  The
    # generated fallback names are namespaced and deterministic by external ID.
    if username or email or display_name:
        conflict_query = Q()
        if username:
            conflict_query |= Q(username=username)
        if email:
            conflict_query |= Q(email=email)
        if display_name:
            conflict_query |= Q(nick_name=display_name)
        if User.objects.filter(conflict_query).exists():
            raise PortalSSOServiceError(PortalSSOErrorCode.BIND_REQUIRED)

    generated_username = f"portal_{hashlib.sha256(external_id.encode('utf-8')).hexdigest()[:48]}"
    if not username:
        username = generated_username
    if not display_name:
        display_name = username
    # A generated collision is treated as a binding problem rather than
    # silently attaching the external identity to an existing account.
    if User.objects.filter(Q(username=username) | Q(nick_name=display_name)).exists():
        raise PortalSSOServiceError(PortalSSOErrorCode.BIND_REQUIRED)

    now = timezone.now()
    try:
        with transaction.atomic():
            user = User.objects.create(
                username=username,
                nick_name=display_name,
                email=email,
                phone="",
                password=password_encrypt(secrets.token_urlsafe(48)),
                role=RoleConstants.USER.value.name,
                source="PORTAL",
                is_active=True,
            )
            identity = UserExternalIdentity.objects.create(
                provider=provider,
                external_user_id=external_id,
                user=user,
                external_username=payload.get("username") or "",
                display_name=payload.get("display_name") or "",
                email=email,
                department_code=payload.get("department_code") or "",
                status=UserExternalIdentity.Status.ACTIVE,
                last_login_at=now,
                meta={},
            )
    except IntegrityError as exc:
        # A concurrent bind/provision race is deliberately not auto-bound.
        raise PortalSSOServiceError(PortalSSOErrorCode.BIND_REQUIRED) from exc
    return user, identity


def exchange_portal_ticket(
    ticket: str,
    *,
    config: PortalSSOConfig,
    request_id: str | None = None,
    rate_limit_subject: str = "unknown",
    cache_backend=None,
    provider: str = "PORTAL",
) -> tuple[dict[str, Any], str]:
    """Consume a one-time ticket, resolve its user, and issue a normal session."""

    correlation_id = _request_id(request_id)
    backend = _cache_backend(cache_backend)
    _require_enabled(config)
    if not _rate_limit(backend, "exchange", rate_limit_subject):
        _audit("exchange", "rate_limited", correlation_id, config.client_id)
        raise PortalSSOServiceError(PortalSSOErrorCode.RATE_LIMITED)

    ticket_text = _safe_ticket_text(ticket)
    ticket_key = _digest_cache_key("ticket", ticket_text)
    used_key = _digest_cache_key("ticket-used", ticket_text)
    try:
        if not backend.add(used_key, 1, timeout=max(1, config.ticket_ttl_seconds), version=_cache_version()):
            _audit("exchange", "ticket_replay", correlation_id, config.client_id)
            raise PortalSSOServiceError(PortalSSOErrorCode.TICKET_INVALID)
        ticket_record = backend.get(ticket_key, version=_cache_version())
        backend.delete(ticket_key, version=_cache_version())
    except PortalSSOServiceError:
        raise
    except Exception as exc:
        raise PortalSSOServiceError(PortalSSOErrorCode.UNAVAILABLE) from exc
    if not isinstance(ticket_record, Mapping):
        _audit("exchange", "ticket_invalid", correlation_id, config.client_id)
        raise PortalSSOServiceError(PortalSSOErrorCode.TICKET_INVALID)
    if ticket_record.get("client_id") != config.client_id:
        raise PortalSSOServiceError(PortalSSOErrorCode.TICKET_INVALID)
    identity_payload = ticket_record.get("identity")
    try:
        validated = validate_portal_payload(identity_payload, config.allowed_targets)
    except (PortalSSOValidationError, TypeError) as exc:
        raise PortalSSOServiceError(PortalSSOErrorCode.TICKET_INVALID) from exc
    target = ticket_record.get("target") or validated.get("target")
    if target is None or target not in config.allowed_targets:
        raise PortalSSOServiceError(PortalSSOErrorCode.TICKET_INVALID)

    try:
        user, _identity = _resolve_portal_user(validated, config, provider=provider)
    except PortalSSOServiceError as exc:
        _audit(
            "exchange",
            exc.code,
            correlation_id,
            config.client_id,
            external_user_id=validated.get("external_user_id"),
        )
        raise

    from .session import issue_system_user_session

    token_data, file_token = issue_system_user_session(user)
    _audit(
        "exchange",
        "success",
        correlation_id,
        config.client_id,
        user_id=str(user.id),
        external_user_id=validated.get("external_user_id"),
    )
    return {"token": token_data["token"], "target": target}, file_token


# Explicit aliases make the service easy to consume from serializers or
# management tooling without coupling them to endpoint class names.
issue_portal_ticket = create_portal_ticket
consume_portal_ticket = exchange_portal_ticket
