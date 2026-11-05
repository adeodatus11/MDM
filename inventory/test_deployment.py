import io
from base64 import b32decode
from pathlib import Path
import sqlite3
import tempfile
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from axes.helpers import get_client_ip_address


@override_settings(REQUIRE_MFA=True)
class MFATests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("mfa-test", password="test-only-strong-password")

    def login_password(self):
        self.client.get("/account/login/")
        return self.client.post("/account/login/", {"login_view-current_step": "auth",
            "auth-username": self.user.username, "auth-password": "test-only-strong-password"})

    def test_password_session_does_not_unlock_application_or_admin(self):
        self.client.force_login(self.user)
        for url in ["/", "/api/devices/", "/devices/new/", "/reports/devices.csv", "/admin/", "/admin/login/"]:
            self.assertRedirects(self.client.get(url), "/account/two_factor/setup/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/account/two_factor/setup/").status_code, 200)

    def test_login_requires_valid_second_factor(self):
        device = TOTPDevice.objects.create(user=self.user, name="default")
        response = self.login_password()
        self.assertEqual(response.context["wizard"]["steps"].current, "token")
        self.assertNotIn("_auth_user_id", self.client.session)
        code = f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"
        response = self.client.post("/account/login/", {"login_view-current_step": "token", "token-otp_token": code})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/api/devices/").status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_bad_token_is_denied(self):
        device = TOTPDevice.objects.create(user=self.user, name="default")
        self.login_password()
        # Not a valid numeric token: rejected without creating a verified session.
        response = self.client.post("/account/login/", {"login_view-current_step": "token", "token-otp_token": "abcdef"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)
        self.assertEqual(self.client.get("/api/devices/").status_code, 302)

    def test_another_users_device_cannot_verify_session(self):
        other = User.objects.create_user("other-mfa")
        device = TOTPDevice.objects.create(user=other, name="default")
        self.client.force_login(self.user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        self.assertEqual(self.client.get("/api/devices/").status_code, 302)

    def test_mfa_cannot_be_disabled(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post("/account/two_factor/disable/", {"understand": True}).status_code, 403)

    def test_enrollment_does_not_use_external_cdn(self):
        self.client.force_login(self.user)
        response = self.client.get("/account/two_factor/setup/")
        self.assertNotContains(response, "cdnjs.cloudflare.com")
        self.assertContains(response, "School RMM")

    def test_first_login_enrollment_requires_confirmation_and_generates_qr(self):
        self.assertEqual(self.login_password().status_code, 302)
        self.assertRedirects(self.client.get("/"), "/account/two_factor/setup/", fetch_redirect_response=False)
        self.client.get("/account/two_factor/setup/")
        response = self.client.post("/account/two_factor/setup/", {"setup_view-current_step": "welcome"})
        self.assertEqual(response.context["wizard"]["steps"].current, "generator")
        self.assertFalse(TOTPDevice.objects.filter(user=self.user, confirmed=True).exists())
        qr = self.client.get("/account/two_factor/qrcode/")
        self.assertEqual(qr.status_code, 200)
        self.assertIn("svg", qr["Content-Type"])
        key = b32decode(response.context["secret_key"])
        response = self.client.post("/account/two_factor/setup/", {"setup_view-current_step": "generator",
            "generator-token": f"{totp(key):06d}"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TOTPDevice.objects.filter(user=self.user, confirmed=True).exists())
        self.assertEqual(self.client.get("/api/devices/").status_code, 200)

    def test_health_is_available_without_authentication(self):
        self.assertEqual(self.client.get("/healthz/").status_code, 200)


class ProxyTests(SimpleTestCase):
    @override_settings(AXES_IPWARE_PROXY_COUNT=0, AXES_IPWARE_META_PRECEDENCE_ORDER=("REMOTE_ADDR",))
    def test_untrusted_forwarded_ip_ignored(self):
        request = RequestFactory().get("/", REMOTE_ADDR="192.168.1.2", HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertEqual(get_client_ip_address(request), "192.168.1.2")

    @override_settings(AXES_IPWARE_PROXY_COUNT=0, AXES_IPWARE_META_PRECEDENCE_ORDER=("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"))
    def test_sanitized_proxy_address(self):
        request = RequestFactory().get("/", REMOTE_ADDR="172.20.0.2", HTTP_X_FORWARDED_FOR="192.168.0.42")
        self.assertEqual(get_client_ip_address(request), "192.168.0.42")

    @override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
    def test_forwarded_https_is_recognized(self):
        self.assertTrue(RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="https").is_secure())


class BackupTests(SimpleTestCase):
    def test_sqlite_backup_restore_and_refusal_to_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            output = Path(directory) / "backup.sqlite3"
            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE evidence (value TEXT)")
                db.execute("INSERT INTO evidence VALUES ('preserved')")
            config = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": source}}
            with override_settings(DATABASES=config):
                call_command("backup_database", output=str(output), stdout=io.StringIO())
                with self.assertRaises(CommandError):
                    call_command("backup_database", output=str(output), stdout=io.StringIO())
            with sqlite3.connect(output) as restored:
                self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(restored.execute("SELECT value FROM evidence").fetchone(), ("preserved",))
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
