import os
from pathlib import Path
import sqlite3
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Wykonuje spójną kopię SQLite bez zatrzymywania usługi, z kontrolą integralności."
    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        config = settings.DATABASES["default"]
        if config["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("Dla innej bazy użyj narzędzia backupu jej silnika.")
        output = Path(options["output"])
        created = False
        try:
            with open(output, "xb", opener=lambda p, f: os.open(p, f, 0o600)):
                created = True
            with sqlite3.connect(Path(config["NAME"]).resolve().as_uri() + "?mode=ro", uri=True) as source:
                with sqlite3.connect(output) as target:
                    source.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise CommandError("Kopia nie przeszła kontroli integralności.")
        except (OSError, sqlite3.Error, CommandError) as exc:
            if created:
                output.unlink(missing_ok=True)
            raise CommandError(f"Nie wykonano kopii: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Kopia SQLite poprawna: {output}. Chroń ją jak dane uwierzytelniania MFA."))
