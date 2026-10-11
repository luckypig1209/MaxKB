"""Anonymous portal SSO ticket and exchange endpoints."""

from common import result
from common.exception.app_exception import AppApiException
from maxkb.const import CONFIG
from rest_framework.request import Request
from rest_framework.views import APIView
from users.serializers.portal_sso import PortalTicketExchangeSerializer, PortalTicketRequestSerializer
from users.services.portal_sso import (
    LEGACY_PORTAL_FIELDS,
    PortalSSOServiceError,
    PortalSSOValidationError,
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


def _is_legacy_portal_body(data) -> bool:
    if not hasattr(data, "keys"):
        return False
    try:
        fields = set(data)
    except TypeError:
        return False
    return fields <= LEGACY_PORTAL_FIELDS and {"username", "signature", "timestamp"} <= fields


class PortalTicketView(APIView):
    """Exchange a portal-signed identity assertion for a short-lived ticket.

    The unmodified portal posts its existing HMAC-SHA1 body.  Callers that
    send the newer signed headers continue to use that protocol.
    """

    def post(self, request: Request):
        config = _config()
        if _is_legacy_portal_body(request.data):
            try:
                ticket_data = create_legacy_portal_ticket(
                    request.data,
                    config=config,
                    request_id=_request_id(request),
                    rate_limit_subject=_rate_limit_subject(request),
                )
            except PortalSSOServiceError as exc:
                raise _service_exception(exc) from exc
            return result.success(ticket_data)
        serializer = PortalTicketRequestSerializer(data=request.data, context={"config": config})
        serializer.is_valid(raise_exception=True)
        client_id = request.META.get("HTTP_X_BIA_CLIENT_ID", "")
        timestamp = request.META.get("HTTP_X_BIA_TIMESTAMP", "")
        nonce = request.META.get("HTTP_X_BIA_NONCE", "")
        signature = request.META.get("HTTP_X_BIA_SIGNATURE", "")
        try:
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
        except PortalSSOServiceError as exc:
            raise _service_exception(exc) from exc
        return result.success(ticket_data)


class PortalTicketExchangeView(APIView):
    """Consume an opaque one-time ticket and issue a normal MaxKB session."""

    def post(self, request: Request):
        config = _config()
        serializer = PortalTicketExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token_data, file_token = exchange_portal_ticket(
                serializer.validated_data["ticket"],
                config=config,
                request_id=_request_id(request),
                rate_limit_subject=_rate_limit_subject(request),
            )
        except PortalSSOServiceError as exc:
            raise _service_exception(exc) from exc
        response = result.success(token_data)
        return _set_file_auth_cookie(response, request, file_token)


# Names kept explicit for URL/API code and future schema references.
PortalTicketsView = PortalTicketView
PortalExchangeView = PortalTicketExchangeView
PortalSSOTicketsView = PortalTicketView
PortalSSOExchangeView = PortalTicketExchangeView
