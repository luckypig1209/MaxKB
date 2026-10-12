"""Anonymous portal SSO ticket and exchange endpoints."""

import json
from collections.abc import Mapping

from common import result
from common.exception.app_exception import AppApiException
from maxkb.const import CONFIG
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.views import APIView
from users.serializers.portal_sso import PortalTicketExchangeSerializer, PortalTicketRequestSerializer
from users.services.portal_sso import (
    PortalSSOErrorCode,
    PortalSSOServiceError,
    PortalSSOValidationError,
    classify_legacy_mapping,
    create_legacy_portal_ticket,
    create_portal_ticket,
    exchange_portal_ticket,
)

_PUBLIC_MESSAGES = {
    "SSO_DISABLED": "Portal SSO is disabled",
    "SSO_CONFIG_INVALID": "Portal SSO is unavailable",
    "SSO_INVALID_REQUEST": "Invalid portal SSO request",
    "SSO_INVALID_SIGNATURE": "Invalid portal SSO request",
    "SSO_TIMESTAMP_INVALID": "Invalid portal SSO request",
    "SSO_NONCE_REPLAY": "Invalid portal SSO request",
    "SSO_TICKET_INVALID": "Invalid portal SSO ticket",
    "SSO_BIND_REQUIRED": "Portal identity requires administrator binding",
    "SSO_USER_DISABLED": "Portal identity is disabled",
    "SSO_RATE_LIMITED": "Too many portal SSO requests",
    "SSO_UNAVAILABLE": "Portal SSO is temporarily unavailable",
}


def _config():
    try:
        return CONFIG.get_portal_sso_config()
    except PortalSSOValidationError as exc:
        error = AppApiException("SSO_CONFIG_INVALID", _PUBLIC_MESSAGES["SSO_CONFIG_INVALID"])
        error.status_code = 503
        raise error from exc


def _request_id(request: Request) -> str | None:
    return request.META.get("HTTP_X_REQUEST_ID")


def _rate_limit_subject(request: Request) -> str:
    # Do not bucket by the unverified client ID: an attacker could rotate that
    # header to evade the anonymous endpoint's per-source limiter.
    return request.META.get("REMOTE_ADDR") or "unknown"


def _service_exception(exc: PortalSSOServiceError) -> AppApiException:
    error = AppApiException(exc.code, _PUBLIC_MESSAGES.get(exc.code, "Portal SSO request failed"))
    error.status_code = exc.status_code
    return error


def _set_file_auth_cookie(response, request: Request, file_token: str):
    """Keep the cookie contract byte-for-byte aligned with ``LoginView``."""

    is_https = request.scheme == "https"
    response.set_cookie(
        key="mk_file_auth",
        value=file_token,
        max_age=7 * 24 * 3600,
        path=CONFIG.get_admin_path(),
        secure=is_https,
        httponly=True,
        samesite="None" if is_https else "Lax",
    )
    return response


def _json_object(raw):
    if not isinstance(raw, (bytes, str)) or not raw:
        return None
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        parsed = json.loads(text)
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _request_body(request: Request):
    """Read the raw body before ``request.data`` consumes the stream."""

    try:
        return request.body
    except Exception:
        return None


def classify_portal_request(request: Request):
    """Return ``(protocol, payload, reason, meta)`` for one ticket request.

    JSON is preferred from ``request.data``.  A raw body captured first is
    used only when the parsed value is not already a legacy body.  A legacy
    attempt does not fall through to the header-signed protocol.
    """

    raw = _request_body(request)
    try:
        data = request.data
    except Exception:
        data = None
    protocol, payload, reason, meta = classify_legacy_mapping(data)
    if protocol == "legacy":
        return protocol, payload, reason, meta
    parsed = _json_object(raw)
    if parsed is not None:
        raw_protocol, raw_payload, raw_reason, raw_meta = classify_legacy_mapping(parsed)
        if raw_protocol == "legacy" or protocol != "v2":
            return raw_protocol, raw_payload, raw_reason, raw_meta
    return protocol, payload, reason, meta


def _log_portal_classify(request: Request, config, reason: str, meta: Mapping) -> None:
    try:
        from common.utils.logger import maxkb_logger

        maxkb_logger.info(
            "portal_sso event=ticket outcome=classify request_id=%s client_id=%s reason=%s "
            "field_count=%s has_username=%s has_signature=%s has_timestamp=%s",
            _request_id(request) or "",
            getattr(config, "client_id", "") or "",
            reason,
            meta.get("field_count", ""),
            "true" if meta.get("has_username") else "false",
            "true" if meta.get("has_signature") else "false",
            "true" if meta.get("has_timestamp") else "false",
        )
    except Exception:
        return None


def _log_portal_sso_failure(request: Request, stage: str, exc: Exception) -> None:
    try:
        from common.utils.logger import maxkb_logger

        maxkb_logger.error(
            "portal_sso event=ticket outcome=unavailable request_id=%s stage=%s error_type=%s",
            _request_id(request),
            stage,
            type(exc).__name__,
        )
    except Exception:
        return None


class PortalTicketView(APIView):
    """Exchange a portal-signed identity assertion for a short-lived ticket.

    The unmodified portal posts its existing HMAC-SHA1 body.  Callers that
    send the newer signed headers continue to use that protocol.
    """

    def post(self, request: Request):
        try:
            return self._post(request)
        except AppApiException:
            raise
        except PortalSSOServiceError as exc:
            raise _service_exception(exc) from exc
        except serializers.ValidationError as exc:
            raise _service_exception(PortalSSOServiceError(PortalSSOErrorCode.INVALID_REQUEST)) from exc
        except Exception as exc:
            _log_portal_sso_failure(request, "ticket_store", exc)
            raise _service_exception(PortalSSOServiceError(PortalSSOErrorCode.UNAVAILABLE)) from exc

    def _post(self, request: Request):
        config = _config()
        protocol, legacy_payload, reason, meta = classify_portal_request(request)
        _log_portal_classify(request, config, reason, meta)
        if protocol == "legacy":
            ticket_data = create_legacy_portal_ticket(
                legacy_payload,
                config=config,
                request_id=_request_id(request),
                rate_limit_subject=_rate_limit_subject(request),
            )
            return result.success(ticket_data)
        if protocol != "v2":
            raise _service_exception(PortalSSOServiceError(PortalSSOErrorCode.INVALID_REQUEST))
        serializer = PortalTicketRequestSerializer(data=request.data, context={"config": config})
        serializer.is_valid(raise_exception=True)
        client_id = request.META.get("HTTP_X_BIA_CLIENT_ID", "")
        timestamp = request.META.get("HTTP_X_BIA_TIMESTAMP", "")
        nonce = request.META.get("HTTP_X_BIA_NONCE", "")
        signature = request.META.get("HTTP_X_BIA_SIGNATURE", "")
        ticket_data = create_portal_ticket(
            serializer.validated_data,
            config=config,
            client_id=client_id,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
            path=request.path,
            request_id=_request_id(request),
            rate_limit_subject=_rate_limit_subject(request),
        )
        return result.success(ticket_data)


class PortalTicketExchangeView(APIView):
    """Consume an opaque one-time ticket and issue a normal MaxKB session."""

    def post(self, request: Request):
        try:
            return self._post(request)
        except AppApiException:
            raise
        except PortalSSOServiceError as exc:
            raise _service_exception(exc) from exc
        except serializers.ValidationError as exc:
            raise _service_exception(PortalSSOServiceError(PortalSSOErrorCode.TICKET_INVALID)) from exc
        except Exception as exc:
            _log_portal_sso_failure(request, "ticket_store", exc)
            raise _service_exception(PortalSSOServiceError(PortalSSOErrorCode.UNAVAILABLE)) from exc

    def _post(self, request: Request):
        config = _config()
        serializer = PortalTicketExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_data, file_token = exchange_portal_ticket(
            serializer.validated_data["ticket"],
            config=config,
            request_id=_request_id(request),
            rate_limit_subject=_rate_limit_subject(request),
        )
        response = result.success(token_data)
        return _set_file_auth_cookie(response, request, file_token)


# Names kept explicit for URL/API code and future schema references.
PortalTicketsView = PortalTicketView
PortalExchangeView = PortalTicketExchangeView
PortalSSOTicketsView = PortalTicketView
PortalSSOExchangeView = PortalTicketExchangeView
