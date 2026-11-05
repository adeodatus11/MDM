import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from inventory.models import AuditEvent, Device, Room

FIELDS = {"name", "os_family", "os_version", "os_release", "os_edition", "os_build", "cpu", "ram_gb", "disk_gb", "ip_address"}
REQUIRED = {"name", "os_family", "os_version", "os_release", "os_edition", "os_build"}


class Command(BaseCommand):
    help = "Importuje lokalny raport inwentaryzacji. Nie instaluje agenta i nie potwierdza ESU."
    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--room", type=int, required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            room = Room.objects.select_related("school").get(pk=options["room"])
            path = Path(options["file"])
            if path.stat().st_size > 5_000_000:
                raise ValueError("Raport jest zbyt duży (maksymalnie 5 MB).")
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            records = payload if isinstance(payload, list) else [payload]
            if not 1 <= len(records) <= 1000:
                raise ValueError("Oczekiwano 1–1000 raportów.")
            seen = set()
            for record in records:
                if not isinstance(record, dict) or not REQUIRED.issubset(record):
                    raise ValueError("Raport nie zawiera wymaganych pól systemu i nazwy.")
                if set(record) - FIELDS:
                    raise ValueError("Raport zawiera nieobsługiwane pola. ESU i capabilities nie są przyjmowane z raportu.")
                name = record["name"]
                if not isinstance(name, str) or not name.strip() or name in seen:
                    raise ValueError("Nazwa komputera jest pusta albo zduplikowana.")
                seen.add(name)
                device = Device.objects.filter(room=room, name=name).first() or Device(room=room, name=name)
                if device.is_demo:
                    raise ValueError("Nie można nadpisać danych demonstracyjnych raportem urządzenia.")
                old_os = (device.os_version, device.os_edition, device.os_build)
                for key in FIELDS & set(record):
                    setattr(device, key, record[key])
                if old_os != (device.os_version, device.os_edition, device.os_build):
                    device.esu_status = "not_applicable" if device.os_version == "11" else "unknown"
                    device.esu_evidence = ""
                    device.esu_valid_until = device.esu_verified_at = None
                device.full_clean()
                device.save()
                AuditEvent.objects.create(school=room.school, action="inventory.imported.cli", object_name=device.name)
        except (OSError, ValueError, TypeError, ValidationError, Room.DoesNotExist) as exc:
            raise CommandError(f"Import przerwany; wycofano wszystkie wpisy: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Zaimportowano {len(records)} raportów. Połączenia agentów i ESU nie zostały potwierdzone."))
