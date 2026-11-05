"""Verify the local Compose stack over real HTTPS without displaying test credentials."""
import argparse
from http.cookiejar import CookieJar
import json
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import urllib.parse
import urllib.request
from django_otp.oath import totp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://localhost:8443")
    parser.add_argument("--ca-file", default="deploy/runtime/test-ca.crt")
    parser.add_argument("--recreate", action="store_true", help="Also recreate the local test stack and verify the session survives.")
    args = parser.parse_args()
    origin = urllib.parse.urlsplit(args.url)
    if origin.scheme != "https" or origin.hostname not in ("localhost", "127.0.0.1") or origin.path:
        parser.error("Test dotyczy wyłącznie lokalnego HTTPS; nie uruchamiaj go na serwerze produkcyjnym.")
    base = args.url
    root = Path(__file__).resolve().parent
    compose_base = ["docker", "compose", "-f", str(root / "compose.yaml")]
    compose = compose_base + ["exec", "-T", "app", "python", "manage.py", "shell", "-c"]
    credentials = {"username": "deployment-check-" + secrets.token_hex(8),
                   "password": secrets.token_urlsafe(32), "key": secrets.token_hex(20)}

    def execute(code, payload):
        result = subprocess.run(compose + [code], input=json.dumps(payload), text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError("Polecenie kontrolne w kontenerze nie powiodło się; sprawdź logi usługi.")

    browser = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=args.ca_file)),
        urllib.request.HTTPCookieProcessor(CookieJar()))

    def fetch(path, form=None):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        request = urllib.request.Request(base + path, data=data, headers={"Referer": base + path})
        with browser.open(request, timeout=15) as response:
            return response.read().decode()

    def token(html):
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)[1]

    if json.loads(fetch("/healthz/"))["status"] != "ok":
        raise RuntimeError("Brak gotowości aplikacji.")
    fetch("/static/inventory/app.css")
    created = False
    try:
        execute("import json,sys; from django.contrib.auth.models import User; "
            "from django_otp.plugins.otp_totp.models import TOTPDevice; d=json.load(sys.stdin); "
            "u=User.objects.create_superuser(d['username'], password=d['password']); "
            "TOTPDevice.objects.create(user=u, name='default', key=d['key'])", credentials)
        created = True
        page = fetch("/account/login/")
        page = fetch("/account/login/", {"csrfmiddlewaretoken": token(page),
            "login_view-current_step": "auth", "auth-username": credentials["username"],
            "auth-password": credentials["password"]})
        if 'name="token-otp_token"' not in page:
            raise RuntimeError("Logowanie nie poprosiło o wymagany drugi składnik.")
        code = f"{totp(bytes.fromhex(credentials['key'])):06d}"
        page = fetch("/account/login/", {"csrfmiddlewaretoken": token(page),
            "login_view-current_step": "token", "token-otp_token": code})
        if "Komputery w szkole" not in page:
            raise RuntimeError("Logowanie z MFA nie otworzyło panelu.")
        if "devices" not in json.loads(fetch("/api/devices/")):
            raise RuntimeError("API nie zwróciło autoryzowanej ewidencji.")
        print("HTTPS, zaufanie CA, style, logowanie hasłem + TOTP i dostęp do API: OK.")
        if args.recreate:
            subprocess.run(compose_base + ["up", "-d", "--no-build", "--force-recreate", "--wait", "--wait-timeout", "60"], check=True)
            if "devices" not in json.loads(fetch("/api/devices/")):
                raise RuntimeError("Sesja lub dane nie przetrwały odtworzenia kontenerów.")
            print("Odtworzenie kontenerów zachowało bazę, klucz sesji, CA i uwierzytelnioną sesję MFA: OK.")
    finally:
        if created:
            execute("import json,sys; from django.contrib.auth.models import User; d=json.load(sys.stdin); "
                    "User.objects.get(username=d['username']).delete()", {"username": credentials["username"]})
            print("Tymczasowe konto kontrolne usunięte. Nie zapisano hasła ani klucza TOTP w plikach.")


if __name__ == "__main__":
    main()
