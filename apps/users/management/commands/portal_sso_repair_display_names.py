"""Repair nicknames of isolated portal accounts.

The internal username stays ``portal_<hash>``. Only accounts whose nickname
still copies that username are rewritten to a friendly label. Dry-run is the
default; ``--apply`` writes the change.
"""

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from users.models import User
from users.models.external_identity import UserExternalIdentity
from users.services.portal_sso import available_portal_display_name


class Command(BaseCommand):
    help = "Repair nicknames of isolated portal accounts without changing usernames"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write nickname changes. Without this flag the command only previews.",
        )

    def handle(self, *args, **options):
        candidates = []
        users = User.objects.filter(source="PORTAL", username__startswith="portal_").order_by("id")
        for user in users.iterator():
            if user.nick_name != user.username:
                continue
            identity = (
                UserExternalIdentity.objects.filter(provider="PORTAL", user_id=user.id).order_by("id").first()
            )
            if identity is None:
                continue
            nick = available_portal_display_name(
                identity.external_username or None,
                identity.external_user_id,
                exclude_user_id=user.id,
            )
            if not nick or nick == user.nick_name:
                continue
            candidates.append((user.id, nick))

        self.stdout.write(f"candidates={len(candidates)}")
        for user_id, _nick in candidates:
            self.stdout.write(f"user_id={user_id}")
        if not options["apply"]:
            self.stdout.write("updated=0")
            return

        updated = 0
        skipped = 0
        for user_id, nick in candidates:
            try:
                with transaction.atomic():
                    user = User.objects.select_for_update().get(id=user_id)
                    if user.source != "PORTAL" or not str(user.username).startswith("portal_"):
                        skipped += 1
                        continue
                    if user.nick_name != user.username:
                        skipped += 1
                        continue
                    if User.objects.filter(nick_name=nick).exclude(id=user.id).exists():
                        skipped += 1
                        continue
                    user.nick_name = nick
                    user.save(update_fields=["nick_name", "update_time"])
                    updated += 1
            except (User.DoesNotExist, IntegrityError):
                skipped += 1
        self.stdout.write(f"updated={updated}")
        self.stdout.write(f"skipped={skipped}")
