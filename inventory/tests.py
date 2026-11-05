import csv
import io
import json
import tempfile
import re
import secrets
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from datetime import date, timedelta
from pathlib import Path
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, LiveServerTestCase, TestCase, override_settings
from django.utils import timezone
from .domain import capabilities, policy_preview, support_status
from .models import AuditEvent, Device, Membership, Room, School


class InventoryTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Szkoła A")
        self.room = Room.objects.create(school=self.school, building="A", floor="1", name="101")
        self.other_school = School.objects.create(name="Szkoła B")
        self.other_room = Room.objects.create(school=self.other_school, building="B", floor="0", name="201")
        self.user = User.objects.create_user("technik", password="test-only-strong-password")
        Membership.objects.create(user=self.user, school=self.school, role="technician")
        self.device = self.make_device()
        self.client.force_login(self.user)

    def make_device(self, **kwargs):
        fields = dict(room=self.room, name="HAN02-u01", os_version="11", os_release="25H2",
                      os_edition="Pro", os_build="26200.100", esu_status="not_applicable")
        fields.update(kwargs)
        return Device.objects.create(**fields)

    def win10(self, **kwargs):
        fields = dict(name="Win10", os_version="10", os_release="22H2", os_build="19045", esu_status="unknown")
        fields.update(kwargs)
        return self.make_device(**fields)

    def test_four_combinations(self):
        for version in ("10", "11"):
            for edition in ("Home", "Pro"):
                with self.subTest(version=version, edition=edition):
                    device = self.make_device(name=f"{version}-{edition}", os_version=version,
                        os_edition=edition, os_release="22H2" if version == "10" else "25H2",
                        os_build="19045" if version == "10" else "26200", esu_status="unknown")
                    device.full_clean()
                    caps = capabilities(device)
                    self.assertEqual(caps["local_group_policy"]["available"], edition == "Pro")
                    self.assertTrue(caps["inventory"]["available"])
                    self.assertFalse(caps["remote_desktop"]["available"])

    def test_unknown_esu_never_means_supported(self):
        self.assertEqual(support_status(self.win10()), "unknown")

    def test_no_esu_means_risk(self):
        self.assertEqual(support_status(self.win10(esu_status="inactive")), "at_risk")

    def test_verified_esu_and_expiry(self):
        d = self.win10(esu_status="active", esu_valid_until=date(2026, 12, 1),
            esu_verified_at=timezone.now(), esu_evidence="Kontrola uprawnienia ESU")
        today = d.esu_verified_at.date()
        d.esu_valid_until = today + timedelta(days=10)
        self.assertEqual(support_status(d, today), "supported")
        self.assertEqual(support_status(d, today + timedelta(days=11)), "at_risk")

    def test_esu_evidence_expires_after_30_days(self):
        d = self.win10(esu_status="active", esu_valid_until=date(2099, 1, 1),
            esu_verified_at=timezone.now() - timedelta(days=31), esu_evidence="Stare potwierdzenie")
        self.assertEqual(support_status(d), "unknown")

    def test_active_esu_requires_evidence(self):
        with self.assertRaises(ValidationError):
            self.win10(esu_status="active").full_clean()

    def test_unsupported_win10_build(self):
        self.assertEqual(support_status(self.win10(os_build="19044")), "unsupported")

    def test_windows11_release_lifecycle_and_mismatch(self):
        self.assertEqual(support_status(self.device, date(2026, 11, 5)), "supported")
        self.device.os_release = "24H2"
        self.device.os_build = "26100"
        self.assertEqual(support_status(self.device, date(2026, 11, 5)), "unsupported")
        self.device.os_build = "19045"
        self.assertEqual(support_status(self.device), "unknown")

    def test_unknown_edition_no_pro_capabilities(self):
        self.device.os_edition = "Unknown"
        self.assertFalse(capabilities(self.device)["local_group_policy"]["available"])
        self.assertEqual(support_status(self.device), "unsupported")

    def test_policy_all_three_outcomes(self):
        self.device.os_edition = "Home"
        self.assertEqual(policy_preview(self.device, "inventory")["status"], "compatible")
        preview = policy_preview(self.device, "classroom_pro")
        self.assertEqual(preview["status"], "partial")
        self.assertIn("Pro", preview["missing"][0]["reason"])
        self.assertEqual(policy_preview(self.device, "remote_support")["status"], "incompatible")
        self.assertFalse(preview["execution_enabled"])

    def test_login_required(self):
        self.client.logout()
        for url in ("/", "/devices/new/", "/api/devices/", "/reports/devices.csv"):
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_dashboard_and_detail_render(self):
        response = self.client.get("/")
        self.assertContains(response, self.device.name)
        self.assertContains(self.client.get(f"/devices/{self.device.pk}/"), "Niepodłączony")

    def test_api_tenant_isolation(self):
        other = self.make_device(room=self.other_room, name="TAJNY")
        response = self.client.get("/api/devices/").json()
        self.assertEqual([d["id"] for d in response["devices"]], [self.device.pk])
        self.assertEqual(self.client.get(f"/devices/{other.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/devices/?school={self.other_school.pk}").json()["count"], 0)

    def test_teacher_and_unassigned_denied(self):
        for role in ("teacher", None):
            self.user.membership_set.all().delete()
            if role:
                Membership.objects.create(user=self.user, school=self.school, role=role)
            for url in ("/", "/devices/new/", "/api/devices/", "/reports/devices.csv"):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_superuser_sees_all_schools(self):
        self.make_device(room=self.other_room, name="OTHER")
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.get("/api/devices/").json()["count"], 2)

    def test_filter_edition_risk_compliance_and_export(self):
        self.win10(os_edition="Home", esu_status="inactive")
        query = "?os_version=10&os_edition=Home&support_status=at_risk&policy=classroom_pro&compliance=partial"
        result = self.client.get("/api/devices/" + query).json()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["devices"][0]["esu_status"], "inactive")
        rows = list(csv.reader(io.StringIO(self.client.get("/reports/devices.csv" + query).content.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "Win10")

    def test_csv_injection_escaped(self):
        self.device.name = '=HYPERLINK("evil")'
        self.device.save()
        response = self.client.get("/reports/devices.csv")
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
        self.assertTrue(rows[1][0].startswith("'="))

    def test_xss_escaped(self):
        self.device.name = "<script>alert(1)</script>"
        self.device.save()
        response = self.client.get("/")
        self.assertNotContains(response, self.device.name)
        self.assertContains(response, "&lt;script&gt;")

    def payload(self, **kwargs):
        fields = {"room": self.room.pk, "name": "NEW", "os_family": "Windows", "os_version": "10",
            "os_release": "22H2", "os_edition": "Home", "os_build": "19045", "esu_status": "inactive"}
        fields.update(kwargs)
        return fields

    def test_creation_and_audit(self):
        response = self.client.post("/devices/new/", self.payload())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Device.objects.filter(name="NEW").exists())
        self.assertEqual(AuditEvent.objects.get().actor, self.user)

    def test_cannot_create_in_other_school(self):
        response = self.client.post("/devices/new/", self.payload(room=self.other_room.pk))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Device.objects.filter(name="NEW").exists())

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post("/devices/new/", self.payload()).status_code, 403)

    def test_logout_requires_post(self):
        self.assertEqual(self.client.get("/logout/").status_code, 405)

    def test_login_works_and_brute_force_is_blocked(self):
        self.client.logout()
        response = self.client.post("/login/", {"username": "technik", "password": "test-only-strong-password"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/api/devices/").status_code, 200)
        self.client.logout()
        for _ in range(5):
            self.client.post("/login/", {"username": "technik", "password": "incorrect"})
        response = self.client.post("/login/", {"username": "technik", "password": "test-only-strong-password"})
        self.assertEqual(response.status_code, 429)

    def test_admin_site_is_reserved_for_main_administrator(self):
        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_import_idempotent_atomic_and_no_esu_claims(self):
        record = {k: v for k, v in self.payload().items() if k not in ("room", "esu_status")}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            path.write_text(json.dumps(record))
            call_command("import_inventory", str(path), room=self.room.pk, stdout=io.StringIO())
            call_command("import_inventory", str(path), room=self.room.pk, stdout=io.StringIO())
            self.assertEqual(Device.objects.filter(name="NEW").count(), 1)
            self.assertEqual(Device.objects.get(name="NEW").support_status, "unknown")
            record["name"] = "ROLLBACK"
            path.write_text(json.dumps([record, {"invalid": True}]))
            with self.assertRaises(CommandError):
                call_command("import_inventory", str(path), room=self.room.pk, stdout=io.StringIO())
            self.assertFalse(Device.objects.filter(name="ROLLBACK").exists())
            path.write_text(json.dumps(dict(record, esu_status="active")))
            with self.assertRaises(CommandError):
                call_command("import_inventory", str(path), room=self.room.pk, stdout=io.StringIO())

    @override_settings(DEBUG=True)
    def test_demo_repeatability(self):
        for _ in range(2):
            call_command("seed_demo", stdout=io.StringIO())
        self.assertEqual(Device.objects.filter(is_demo=True).count(), 4)

    @override_settings(DEBUG=False)
    def test_demo_refused_outside_development(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=io.StringIO())

    def test_health(self):
        self.client.logout()
        self.assertEqual(self.client.get("/healthz/").json()["status"], "ok")


class LiveHTTPTests(LiveServerTestCase):
    def test_real_http_login_registration_and_inventory(self):
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user("http-test", password=password)
        school = School.objects.create(name="HTTP test school")
        room = Room.objects.create(school=school, building="Test", floor="0", name="VM")
        Membership.objects.create(user=user, school=school, role="technician")
        # Proxy bypass is limited to this test's loopback server.
        browser = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))
        base = self.live_server_url
        with browser.open(base + "/healthz/", timeout=10) as response:
            self.assertEqual(json.load(response)["status"], "ok")
        with browser.open(base + "/login/", timeout=10) as response:
            token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.read().decode())[1]
        data = urllib.parse.urlencode({"username": user.username, "password": password,
                                      "csrfmiddlewaretoken": token}).encode()
        with browser.open(urllib.request.Request(base + "/login/", data=data), timeout=10) as response:
            self.assertIn("Komputery w szkole", response.read().decode())
        with browser.open(base + "/devices/new/", timeout=10) as response:
            token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.read().decode())[1]
        for version, edition in [("10", "Home"), ("10", "Pro"), ("11", "Home"), ("11", "Pro")]:
            data = urllib.parse.urlencode({"csrfmiddlewaretoken": token, "room": room.pk,
                "name": f"VM-{version}-{edition}", "os_family": "Windows", "os_version": version,
                "os_release": "22H2" if version == "10" else "25H2", "os_edition": edition,
                "os_build": "19045" if version == "10" else "26200",
                "esu_status": "inactive" if version == "10" else "not_applicable"}).encode()
            with browser.open(urllib.request.Request(base + "/devices/new/", data=data), timeout=10) as response:
                self.assertIn(f"VM-{version}-{edition}", response.read().decode())
        with browser.open(base + "/api/devices/?os_version=10&support_status=at_risk", timeout=10) as response:
            result = json.load(response)
        self.assertEqual(result["count"], 2)
        self.assertTrue(all(d["connection_status"] == "not_connected" for d in result["devices"]))
