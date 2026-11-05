from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from inventory.models import Device, Room, School


class Command(BaseCommand):
    help = "Tworzy cztery wyraźnie oznaczone, fikcyjne komputery w lokalnym środowisku testowym."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Dane demonstracyjne wymagają SCHOOL_RMM_DEBUG=true.")
        school, _ = School.objects.get_or_create(name="TEST — Szkoła demonstracyjna")
        room, _ = Room.objects.get_or_create(school=school, building="Budynek testowy", floor="1", name="TEST-02")
        for index, (version, edition) in enumerate([("10", "Home"), ("10", "Pro"), ("11", "Home"), ("11", "Pro")], 1):
            defaults = {"os_version": version, "os_edition": edition,
                "os_release": "22H2" if version == "10" else "25H2",
                "os_build": "19045" if version == "10" else "26200", "is_demo": True,
                "cpu": "Procesor testowy", "ram_gb": 8, "disk_gb": 256,
                "esu_status": "inactive" if index == 1 else "active" if index == 2 else "not_applicable"}
            if index == 2:
                defaults.update(esu_valid_until=timezone.localdate() + timedelta(days=90),
                    esu_verified_at=timezone.now(), esu_evidence="FIKCYJNY PRZYKŁAD — nie stanowi potwierdzenia licencji")
            device, created = Device.objects.get_or_create(room=room, name=f"TEST-HAN02-u{index:02}", defaults=defaults)
            if not device.is_demo:
                raise CommandError("Istnieje rzeczywisty wpis o nazwie testowej; przerwano bez zmian.")
        self.stdout.write(self.style.SUCCESS("Dostępne 4 fikcyjne urządzenia TEST. Nie utworzono konta ani hasła."))
