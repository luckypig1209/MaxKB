from .portal_sso import (
    PortalSSOConfig,
    PortalSSOValidationError,
    canonical_json,
    canonical_json_bytes,
    canonical_request,
    create_portal_ticket,
    consume_portal_ticket,
    exchange_portal_ticket,
    generate_signature,
    PortalSSOErrorCode,
    PortalSSOServiceError,
    sign_request,
    issue_portal_ticket,
    validate_portal_payload,
    validate_timestamp,
    verify_request_signature,
    verify_signature,
)

__all__ = [
    "PortalSSOConfig",
    "PortalSSOValidationError",
    "canonical_json",
    "canonical_json_bytes",
    "canonical_request",
    "create_portal_ticket",
    "consume_portal_ticket",
    "exchange_portal_ticket",
    "generate_signature",
    "PortalSSOErrorCode",
    "PortalSSOServiceError",
    "sign_request",
    "issue_portal_ticket",
    "validate_portal_payload",
    "validate_timestamp",
    "verify_request_signature",
    "verify_signature",
    "issue_system_user_session",
]


def __getattr__(name):
    # Keep protocol-only imports usable by tooling that has not initialized
    # Django yet, while still exposing the shared session service conveniently.
    if name == "issue_system_user_session":
        from .session import issue_system_user_session

        return issue_system_user_session
    raise AttributeError(name)
