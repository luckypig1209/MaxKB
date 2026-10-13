"""Explicitly rebind a portal identity. The default mode is a read-only preview."""

import hashlib
from datetime import timezone as datetime_timezone

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone
from users.models import User
from users.models.external_identity import UserExternalIdentity

REBIND_REASON = "portal_admin_explicit_binding"
PRIVILEGED_ROLES = frozenset({"ADMIN", "WORKSPACE_MANAGE"})


class Command(BaseCommand):
    help = "Preview or explicitly rebind a portal identity to another existing user"

    def add_arguments(self, parser):
        parser.add_argument("--provider", default="PORTAL", help="External identity provider")
        parser.add_argument("--external-user-id", required=True, help="Stable external user ID")
        parser.add_argument("--from-user", required=True, help="Current owner username or UUID")
        parser.add_argument("--to-user", required=True, help="Target username or UUID")
        parser.add_argument("--apply", action="store_true", help="Write the rebind. Omit for a read-only preview")
        parser.add_argument(
            "--disable-source-user",
            action="store_true",
            help="Disable the source user when it is an isolated portal account",
        )
        parser.add_argument(
            "--allow-privileged-target",
            action="store_true",
            help="Required when the target role is ADMIN or WORKSPACE_MANAGE",
        )
        parser.add_argument(
            "--confirm-target-user-id",
            default="",
            help="Full target user UUID. Required for a privileged target",
        )
        parser.add_argument(
            "--enable-target-user",
            action="store_true",
            help="Controlled rollback only: re-enable an isolated portal target user",
        )

    def handle(self, *args, **options):
        provider = self._provider(options["provider"])
        external_user_id = self._external_user_id(options["external_user_id"])
        from_user = self._find_user(options["from_user"], "source")
        to_user = self._find_user(options["to_user"], "target")
        if not options["apply"]:
            identity = UserExternalIdentity.objects.filter(
                provider=provider, external_user_id=external_user_id
            ).first()
            plan = self._evaluate(identity, from_user, to_user, options, applying=False)
            self._render("preview", identity, from_user, to_user, external_user_id, plan)
            return

        with transaction.atomic():
            identity = (
                UserExternalIdentity.objects.select_for_update()
                .filter(provider=provider, external_user_id=external_user_id)
                .first()
            )
            locked = {
                row.id: row
                for row in User.objects.select_for_update()
                .filter(id__in=[from_user.id, to_user.id])
                .order_by("id")
            }
            from_user = locked[from_user.id]
            to_user = locked[to_user.id]
            plan = self._evaluate(identity, from_user, to_user, options, applying=True)
            if plan["outcome"] != "idempotent":
                self._write(identity, from_user, to_user, options)
                plan["outcome"] = "applied"

        from_user.refresh_from_db()
        to_user.refresh_from_db()
        identity.refresh_from_db()
        self._audit(plan["outcome"], to_user, external_user_id)
        self._render("apply", identity, from_user, to_user, external_user_id, plan)

    def _provider(self, provider: str) -> str:
        provider = provider.strip()
        if not provider or len(provider) > 32 or any(ord(char) < 0x20 for char in provider):
            raise CommandError("provider must be a non-empty value no longer than 32 characters")
        return provider

    def _external_user_id(self, external_user_id: str) -> str:
        if (
            not external_user_id
            or len(external_user_id) > 256
            or any(ord(char) < 0x20 for char in external_user_id)
        ):
            raise CommandError("external-user-id must be a non-empty value no longer than 256 characters")
        return external_user_id

    def _find_user(self, user_ref: str, label: str) -> User:
        user = User.objects.filter(username=user_ref).first()
        if user is None:
            try:
                user = User.objects.filter(id=user_ref).first()
            except (TypeError, ValueError, ValidationError):
                user = None
        if user is None:
            raise CommandError(f"{label} user was not found")
        return user

    def _evaluate(self, identity, from_user, to_user, options, *, applying: bool) -> dict:
        if identity is None:
            raise CommandError("external identity was not found; create it with portal_sso_bind before rebinding")
        if identity.status != UserExternalIdentity.Status.ACTIVE:
            raise CommandError("external identity is not active")
        if not isinstance(identity.meta, dict):
            raise CommandError("external identity meta is not an object")
        if identity.user_id == to_user.id:
            self._require_privileged_confirmation(to_user, options, applying=applying)
            return self._plan("idempotent", mapping_updates=0, source_disabled=0, target_enabled=0)

        if identity.user_id != from_user.id:
            raise CommandError("current mapping owner does not match --from-user")
        self._require_target_available(identity, to_user, options)
        self._require_privileged_confirmation(to_user, options, applying=applying)
        if options["disable_source_user"] and not self._is_isolated_portal_user(from_user):
            raise CommandError("source user cannot be disabled because it is not an isolated portal account")
        if options["enable_target_user"] and not self._is_isolated_portal_user(to_user):
            raise CommandError("enable-target-user only applies to an isolated portal account")
        source_disabled = 1 if options["disable_source_user"] and from_user.is_active else 0
        target_enabled = 1 if options["enable_target_user"] and not to_user.is_active else 0
        return self._plan(
            "ready",
            mapping_updates=1,
            source_disabled=source_disabled,
            target_enabled=target_enabled,
        )

    def _require_target_available(self, identity, to_user, options) -> None:
        if UserExternalIdentity.objects.filter(provider=identity.provider, user_id=to_user.id).exclude(
            pk=identity.pk
        ).exists():
            raise CommandError("target user already has an external identity for this provider")
        if to_user.is_active:
            return
        if options["enable_target_user"] and self._is_isolated_portal_user(to_user):
            return
        if options["enable_target_user"]:
            raise CommandError("enable-target-user only applies to an isolated portal account")
        raise CommandError("target user is inactive")

    def _require_privileged_confirmation(self, to_user, options, *, applying: bool) -> None:
        confirm = (options.get("confirm_target_user_id") or "").strip()
        if confirm and confirm != str(to_user.id):
            raise CommandError("confirm-target-user-id does not match the target user")
        if not applying or to_user.role not in PRIVILEGED_ROLES:
            return
        if not options["allow_privileged_target"] or confirm != str(to_user.id):
            raise CommandError("privileged target requires --allow-privileged-target and --confirm-target-user-id")

    def _write(self, identity, from_user, to_user, options) -> None:
        meta = dict(identity.meta or {})
        meta["last_rebind_from_user_id"] = str(from_user.id)
        meta["last_rebind_at"] = timezone.now().astimezone(datetime_timezone.utc).isoformat()
        meta["last_rebind_reason"] = REBIND_REASON
        identity.user = to_user
        identity.meta = meta
        try:
            identity.save(update_fields=["user", "meta", "update_time"])
        except IntegrityError as exc:
            raise CommandError("target user already has an external identity for this provider") from exc

        if options["disable_source_user"]:
            if not self._is_isolated_portal_user(from_user):
                raise CommandError("source user cannot be disabled because it is not an isolated portal account")
            if UserExternalIdentity.objects.filter(
                user_id=from_user.id, status=UserExternalIdentity.Status.ACTIVE
            ).exists():
                raise CommandError("source user still has an active external identity")
            if from_user.is_active:
                from_user.is_active = False
                from_user.save(update_fields=["is_active", "update_time"])

        if options["enable_target_user"]:
            if not self._is_isolated_portal_user(to_user):
                raise CommandError("enable-target-user only applies to an isolated portal account")
            if not to_user.is_active:
                to_user.is_active = True
                to_user.save(update_fields=["is_active", "update_time"])

    def _plan(self, outcome: str, *, mapping_updates: int, source_disabled: int, target_enabled: int) -> dict:
        return {
            "outcome": outcome,
            "mapping_updates": mapping_updates,
            "source_users_disabled": source_disabled,
            "target_users_enabled": target_enabled,
        }

    def _is_isolated_portal_user(self, user: User) -> bool:
        return user.source == "PORTAL" and user.role == "USER" and user.username.startswith("portal_")

    def _audit(self, outcome: str, to_user: User, external_user_id: str) -> None:
        from users.services.portal_sso import _audit

        _audit(
            "rebind",
            outcome,
            "",
            user_id=str(to_user.id),
            external_user_id=external_user_id,
            provision="explicit_rebind",
            reason=REBIND_REASON,
        )

    def _render(self, mode: str, identity, from_user, to_user, external_user_id: str, plan: dict) -> None:
        digest = hashlib.sha256(external_user_id.encode("utf-8")).hexdigest()
        lines = [
            f"mode={mode}",
            f"outcome={plan['outcome']}",
            f"identity_id={identity.id}",
            f"external_user_id_sha256={digest}",
            f"from_user_id={from_user.id}",
            f"from_role={from_user.role}",
            f"from_source={from_user.source}",
            f"from_active={str(from_user.is_active).lower()}",
            f"to_user_id={to_user.id}",
            f"to_role={to_user.role}",
            f"to_source={to_user.source}",
            f"to_active={str(to_user.is_active).lower()}",
            f"mapping_updates={plan['mapping_updates']}",
            "users_created=0",
            "users_deleted=0",
            f"source_users_disabled={plan['source_users_disabled']}",
            f"target_users_enabled={plan['target_users_enabled']}",
            "target_profile_changed=false",
        ]
        self.stdout.write("\n".join(lines))
