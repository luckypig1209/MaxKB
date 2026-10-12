"""Request serializers for the anonymous portal SSO endpoints."""

from collections.abc import Mapping

from rest_framework import serializers
from users.services.portal_sso import (
    DEFAULT_ALLOWED_TARGETS,
    PortalSSOValidationError,
    validate_portal_payload,
)


class PortalTicketRequestSerializer(serializers.Serializer):
    external_user_id = serializers.CharField(required=True, max_length=256)
    username = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=150)
    display_name = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=150)
    email = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=254)
    department_code = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=64)
    target = serializers.CharField(required=False, allow_blank=False, allow_null=False, max_length=512)

    def to_internal_value(self, data):
        # DRF normally drops unknown keys before ``validate``.  SSO signs the
        # complete closed body, so an extension field must be rejected rather
        # than silently removed from the signed representation.
        # A string detail becomes a one-element list, and DRF then builds
        # ``ReturnDict`` from that list.  Keep the detail a mapping.
        if not isinstance(data, Mapping):
            raise serializers.ValidationError({"non_field_errors": ["Invalid portal SSO request"]})
        allowed_targets = getattr(self.context.get("config"), "allowed_targets", DEFAULT_ALLOWED_TARGETS)
        try:
            return validate_portal_payload(data, allowed_targets)
        except PortalSSOValidationError as exc:
            raise serializers.ValidationError({"non_field_errors": ["Invalid portal SSO request"]}) from exc

    def validate(self, attrs):
        return attrs


class PortalTicketExchangeSerializer(serializers.Serializer):
    ticket = serializers.CharField(required=True, max_length=512, allow_blank=False, trim_whitespace=False)

    def to_internal_value(self, data):
        if not isinstance(data, Mapping) or set(data) != {"ticket"}:
            raise serializers.ValidationError({"non_field_errors": ["Invalid portal SSO ticket request"]})
        if not isinstance(data.get("ticket"), str):
            raise serializers.ValidationError({"non_field_errors": ["Invalid portal SSO ticket"]})
        return super().to_internal_value(data)

    def validate_ticket(self, value):
        if len(value) < 43:
            raise serializers.ValidationError("Invalid portal SSO ticket")
        return value


PortalSSOTicketRequestSerializer = PortalTicketRequestSerializer
PortalSSOExchangeSerializer = PortalTicketExchangeSerializer
