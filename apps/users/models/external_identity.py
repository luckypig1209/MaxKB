"""External identities trusted by the portal SSO adapter."""

import uuid_utils.compat as uuid
from django.db import models
from users.models.user import User


class UserExternalIdentity(models.Model):
    """A durable, one-to-one mapping between an external identity and User.

    ``PROTECT`` is intentional: deleting a local user cannot silently delete
    and later recreate an external identity with a different owner.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DISABLED = "DISABLED", "Disabled"

    ACTIVE = Status.ACTIVE
    DISABLED = Status.DISABLED

    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    provider = models.CharField(max_length=32, default="PORTAL", db_index=True)
    external_user_id = models.CharField(max_length=256, db_index=True)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="external_identities")
    external_username = models.CharField(max_length=150, default="", blank=True)
    display_name = models.CharField(max_length=150, default="", blank=True)
    email = models.EmailField(max_length=254, null=True, blank=True)
    department_code = models.CharField(max_length=64, default="", blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    last_login_at = models.DateTimeField(null=True, blank=True, db_index=True)
    meta = models.JSONField(default=dict, blank=True)
    create_time = models.DateTimeField(auto_now_add=True, null=True)
    update_time = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        db_table = "user_external_identity"
        constraints = [  # noqa: RUF012 - Django Meta requires class-level declarations.
            models.UniqueConstraint(
                fields=["provider", "external_user_id"],
                name="user_ext_identity_provider_external_uid_uniq",
            ),
            models.UniqueConstraint(
                fields=["provider", "user"],
                name="user_ext_identity_provider_user_uniq",
            ),
        ]
        indexes = [  # noqa: RUF012 - Django Meta requires class-level declarations.
            models.Index(fields=["user", "status"], name="user_ext_id_user_status_idx"),
        ]
