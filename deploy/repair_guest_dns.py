#!/usr/bin/env python3
"""Diagnose and optionally repair DNS only inside the existing School RMM VM."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import uuid

TARGET = Path('/etc/systemd/resolved.conf.d/90-school-rmm-dns.conf')
BACKUPS = Path('/var/backups/school-rmm')
NAMES = ('registry-1.docker.io', 'auth.docker.io', 'pypi.org', 'files.pythonhosted.org')
EXPECTED_MAC = 'bc:24:11:d5:48:c7'


class DNSError(RuntimeError):
    pass


def run(command, timeout=20):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise DNSError(result.stderr.strip()[-700:] or 'Polecenie nie powiodło się: ' + command[0])
    return result.stdout


def guest_interface():
    if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'school-rmm':
        raise DNSError('Ten skrypt wymaga sudo wewnątrz VM school-rmm. Nie uruchamiać na pve.')
    routes = json.loads(run(['ip', '-j', '-4', 'route', 'show', 'default']))
    iface = routes[0]['dev']
    interfaces = json.loads(run(['ip', '-j', '-4', 'addr', 'show', 'dev', iface, 'scope', 'global']))
    links = json.loads(run(['ip', '-j', 'link', 'show', 'dev', iface]))
    if links[0].get('address', '').lower() != EXPECTED_MAC:
        raise DNSError('Adres MAC nie odpowiada VM 104. Przerwano przed zmianami.')
    addresses = [item['local'] for item in interfaces[0]['addr_info'] if item.get('family') == 'inet']
    if not any(ipaddress.IPv4Address(value) in ipaddress.IPv4Network('192.168.16.0/22') for value in addresses):
        raise DNSError('VM nie ma adresu w szkolnym LAN. Przerwano przed zmianami.')
    return iface, routes[0].get('gateway')


def dns_question(name, record_type):
    labels = name.encode('ascii').split(b'.')
    return b''.join(bytes([len(label)]) + label for label in labels) + b'\x00' + struct.pack('!HH', record_type, 1)


def validate_reply(response, transaction, question, record_type):
    if len(response) < 12 + len(question):
        raise DNSError('Niepełna odpowiedź DNS')
    ident, flags, questions, answers, _, _ = struct.unpack('!6H', response[:12])
    if (ident != transaction or not flags & 0x8000 or flags & 0x7A0F or questions != 1
            or response[12:12 + len(question)] != question):
        raise DNSError('Niepoprawna, ucięta lub błędna odpowiedź DNS')
    # An IPv4-only destination may validly return NOERROR with no AAAA records.
    if record_type == 1 and not answers:
        raise DNSError('Brak rekordów A w odpowiedzi DNS')


def probe_server(server):
    for record_type in (1, 28):
        transaction = secrets.randbelow(65536)
        question = dns_question(NAMES[0], record_type)
        request = struct.pack('!6H', transaction, 0x0100, 1, 0, 0, 0) + question
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
            stream.settimeout(2)
            stream.connect((server, 53))
            stream.send(request)
            validate_reply(stream.recv(4096), transaction, question, record_type)


def native_dns_works():
    code = "import socket,sys\nfor name in sys.argv[1:]:\n socket.getaddrinfo(name,443,type=socket.SOCK_STREAM)\n print(name, 'DNS OK', flush=True)"
    try:
        output = run([sys.executable, '-c', code, *NAMES], timeout=30)
        print(output.strip(), flush=True)
        return True
    except (DNSError, subprocess.TimeoutExpired):
        return False


def apply_dns(server, target=None, backups=None):
    server = str(ipaddress.IPv4Address(server))
    target, backups = target or TARGET, backups or BACKUPS
    if target.is_symlink() or any(parent.is_symlink() for parent in target.parents) or (target.exists() and not target.is_file()):
        raise DNSError('Niestandardowa ścieżka konfiguracji DNS. Przerwano bez nadpisania.')
    backup = backups / ('dns-' + uuid.uuid4().hex[:12])
    backup.mkdir(parents=True, mode=0o700)
    existed = target.exists()
    if existed:
        shutil.copy2(target, backup / target.name)
    (backup / 'previous-dns.txt').write_text(run(['resolvectl', 'dns']))
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + target.name, dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            output.write('# School RMM VM 104 only\n[Resolve]\nDNS=\nDNS=' + server + '\nDomains=~.\n')
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        run(['systemctl', 'restart', 'systemd-resolved'])
        run(['resolvectl', 'flush-caches'])
        if not native_dns_works():
            raise DNSError('Systemowy resolver nadal nie rozwiązuje wymaganych nazw.')
    except BaseException:
        if existed:
            shutil.copy2(backup / target.name, target)
        else:
            target.unlink(missing_ok=True)
        try:
            run(['systemctl', 'restart', 'systemd-resolved'])
        except Exception as rollback_error:
            print('Błąd ponownego uruchomienia resolvera po przywróceniu pliku: ' + str(rollback_error), file=sys.stderr)
        print('Przywrócono poprzedni plik konfiguracji DNS. Kopia: ' + str(backup), file=sys.stderr)
        raise
    finally:
        Path(temporary).unlink(missing_ok=True)
    print('DNS VM 104 naprawiony. Serwer: ' + server + '. Kopia konfiguracji: ' + str(backup))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply a tested DNS override inside VM 104 only.')
    args = parser.parse_args()
    iface, gateway = guest_interface()
    print('VM school-rmm; interfejs: ' + iface, flush=True)
    current_dns = run(['resolvectl', 'dns'])
    print(current_dns.strip(), flush=True)
    if native_dns_works():
        print('DNS już działa. Nie zmieniono konfiguracji.')
        return
    # Prefer configured servers and the local gateway before the resolvers
    # already known from the owner's pve configuration. Never install an
    # untested server or propagate the Tailscale MagicDNS address into this VM.
    configured = []
    for token in current_dns.split():
        try:
            address = ipaddress.IPv4Address(token)
        except ValueError:
            continue
        if not address.is_loopback and not address.is_multicast and str(address) != '100.100.100.100':
            configured.append(str(address))
    candidates = list(dict.fromkeys(value for value in (*configured, gateway, '192.168.0.1', '8.8.8.8') if value))
    selected = None
    for server in candidates:
        try:
            ipaddress.IPv4Address(server)
            probe_server(server)
        except (OSError, ValueError, DNSError) as error:
            print('DNS ' + server + ': ' + str(error), flush=True)
            continue
        print('DNS ' + server + ': poprawne odpowiedzi A i AAAA.', flush=True)
        selected = server
        break
    if selected is None:
        raise DNSError('Żaden sprawdzony serwer DNS nie odpowiada poprawnie. Nie zmieniono konfiguracji VM.')
    if not args.apply:
        print('Test zakończony. Zmiana wymaga --apply; konfiguracja pozostała bez zmian.')
        return
    os.umask(0o077)
    with open('/run/lock/school-rmm-dns.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        apply_dns(selected)


if __name__ == '__main__':
    try:
        main()
    except (DNSError, OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as error:
        print('Naprawa DNS zatrzymana: ' + str(error), file=sys.stderr)
        sys.exit(1)
