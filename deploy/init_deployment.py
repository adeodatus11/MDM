"""Prepare non-secret connection settings and a private key; never print credentials."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--bind-address", default="127.0.0.1")
    parser.add_argument("--https-port", type=int, default=443)
    args = parser.parse_args()
    host = args.hostname.lower()
    if len(host) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.split(".")):
        parser.error("Podaj nazwę DNS lub adres IPv4, bez schematu, ścieżki i portu.")
    try:
        ipaddress.IPv4Address(args.bind_address)
    except ValueError:
        parser.error("Adres nasłuchiwania musi być adresem IPv4.")
    if not 1 <= args.https_port <= 65535:
        parser.error("Port poza zakresem 1–65535.")
    root = Path(__file__).resolve().parent
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    if runtime.is_symlink() or runtime.stat().st_mode & 0o077:
        parser.error("Katalog deploy/runtime musi być prywatnym katalogiem z prawami 0700.")
    config = root / ".env"
    expected = (f"SCHOOL_RMM_HOST={host}\nSCHOOL_RMM_BIND_ADDRESS={args.bind_address}\n"
                f"SCHOOL_RMM_HTTPS_PORT={args.https_port}\n")
    if config.exists() and config.read_text() != expected:
        parser.error("Istnieje inna konfiguracja deploy/.env. Zmień ją świadomie przed wdrożeniem.")
    key = runtime / "django.key"
    if key.is_symlink() or (key.exists() and not key.is_file()):
        parser.error("Klucz musi być zwykłym plikiem wewnątrz prywatnego katalogu runtime.")
    if not key.exists():
        # The parent is 0700. The mounted secret must be readable by non-root UID 10001.
        with open(key, "x", opener=lambda p, f: os.open(p, f, 0o444)) as stream:
            stream.write(secrets.token_urlsafe(64))
    key.chmod(0o444)
    if not config.exists():
        with open(config, "x", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
            stream.write(expected)
    print("Konfiguracja przygotowana. Zachowano istniejący klucz. Nie utworzono kont ani haseł.")


if __name__ == "__main__":
    main()
