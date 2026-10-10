"""Bind an existing MaxKB user to a portal identity."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from users.models import User
from users.models.external_identity import UserExternalIdentity


class Command(BaseCommand):
    help = "Bind a portal external identity to an existing MaxKB user"

    def add_arguments(self, parser):
        parser.add_argument("--provider", default="PORTAL", help="External identity provider")
        parser.add_argument("--external-user-id", required=True, help="Stable external user ID")
        parser.add_argument(
            "--user",
            "--user-id",
            dest="user_ref",
            required=True,
            help="Existing MaxKB user UUID or username",
        )

    def handle(self, *args, **options):
        provider = options["provider"].strip()
        external_user_id = options["external_user_id"]
        user_ref = options["user_ref"]
        if not provider or len(provider) > 32 or any(ord(char) < 0x20 for char in provider):
            raise CommandError("provider must be a non-empty value no longer than 32 characters")
        if not external_user_id or len(external_user_id) > 256 or any(ord(char) < 0x20 for char in external_user_id):
            raise CommandError("external-user-id must be a non-empty value no longer than 256 characters")

        user = User.objects.filter(username=user_ref).first()
        if user is None:
            try:
                user = User.objects.filter(id=user_ref).first()
            except (TypeError, ValueError, ValidationError):
                user = None
        if user is None:
            raise CommandError("target user was not found")

        with transaction.atomic():
            identity = (
                UserExternalIdentity.objects.select_for_update()
                .filter(provider=provider, external_user_id=external_user_id)
                .first()
            )
            if identity is not None:
                if identity.user_id != user.id:
                    raise CommandError("external identity is already bound to another user")
                changed = identity.status != UserExternalIdentity.Status.ACTIVE
                if changed:
                    identity.status = UserExternalIdentity.Status.ACTIVE
                    identity.save(update_fields=["status", "update_time"])
                self.stdout.write(self.style.SUCCESS("External identity is already bound (idempotent)"))
                return

            existing_for_user = (
                UserExternalIdentity.objects.select_for_update().filter(provider=provider, user_id=user.id).first()
            )
            if existing_for_user is not None:
                raise CommandError("target user already has an external identity for this provider")

            try:
                UserExternalIdentity.objects.create(
                    provider=provider,
                    external_user_id=external_user_id,
                    user=user,
                    external_username="",
                    display_name="",
                    email=user.email or None,
                    department_code="",
                    status=UserExternalIdentity.Status.ACTIVE,
                    meta={},
                )
            except IntegrityError as exc:
                raise CommandError("external identity binding conflicts with an existing mapping") from exc

        self.stdout.write(self.style.SUCCESS("External identity bound successfully"))
