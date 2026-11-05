#!/usr/bin/env python3
"""Create or resume the owned School RMM VM on pve via the owner's SSH terminal."""
import argparse
import base64
import fcntl
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

VMID = 104
NODE = "pve"
STORAGE = "local-zfs"
BRIDGE = "vmbr0"
SNIPPET_STORAGE = "school-rmm-104-snippets"
PROTECTED = {100, 101, 103}
REVISION = "32f52e48ba01851211865c0f9b2b74b184b070e5"
SOURCE_URL = f"https://codeload.github.com/adeodatus11/MDM/tar.gz/{REVISION}"
SOURCE_SHA256 = "4b86d7f0aa2f6b7f02fd8b53103cd8414ed660e6b5f86662cf69897f7636d3e5"
IMAGE_NAME = "noble-server-cloudimg-amd64.img"
IMAGE_BASE = "https://cloud-images.ubuntu.com/noble/current/"
STATE_DIR = Path("/var/lib/vz/school-rmm-install")
SNIPPET_ROOT = Path("/var/lib/vz/school-rmm-104-snippets")
GIB = 1024 ** 3
SCHOOL_LAN = "192.168.16.0/22"

# Runs inside the guest. Reusing an extracted archive must never overwrite local
# settings, keys, data, or edited source files.
SOURCE_SETUP = r'''
import hashlib, shutil, sys, tarfile, tempfile
from pathlib import Path, PurePosixPath
archive, root, expected = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit('Archiwum aplikacji nie przeszło kontroli SHA256.')
if root.is_symlink() or (root.exists() and not root.is_dir()):
    raise SystemExit('Katalog aplikacji nie jest zwykłym katalogiem.')
with tarfile.open(archive, 'r:gz') as source:
    entries = []
    for member in source.getmembers():
        parts = PurePosixPath(member.name).parts
        if member.name.startswith('/') or '..' in parts or not (member.isdir() or member.isfile()):
            raise SystemExit('Nieobsługiwany wpis w archiwum aplikacji.')
        if len(parts) > 1:
            entries.append((member, Path(*parts[1:])))
    if not any(str(name) == 'manage.py' for member, name in entries if member.isfile()):
        raise SystemExit('Brak manage.py w zweryfikowanym archiwum.')
    if root.exists():
        for member, name in entries:
            target = root / name
            if any(part.is_symlink() for part in [target, *target.parents] if part != root.parent):
                raise SystemExit('Dowiązanie w katalogu aplikacji: ' + str(name))
            if member.isdir():
                if not target.is_dir():
                    raise SystemExit('Brak katalogu źródłowego: ' + str(name))
            elif not target.is_file() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(source.extractfile(member).read()).digest():
                raise SystemExit('Zmieniony lub niepełny plik: ' + str(name) + '; zachowano dane, wymagane sprawdzenie.')
    else:
        temporary = Path(tempfile.mkdtemp(prefix='.school-rmm-source-', dir=root.parent))
        try:
            for member, name in entries:
                target = temporary / name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as output, source.extractfile(member) as content:
                        shutil.copyfileobj(content, output)
                    target.chmod(member.mode & 0o777)
            temporary.chmod(0o755)
            temporary.rename(root)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
print('Zweryfikowano źródła; zachowano lokalne ustawienia i dane.')
'''


def school_network(value):
    try:
        network = ipaddress.IPv4Network(value, strict=True)
    except ValueError as error:
        raise argparse.ArgumentTypeError('Podaj poprawną sieć IPv4 w zapisie CIDR.') from error
    private = (ipaddress.IPv4Network(block) for block in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    if not any(network.subnet_of(block) for block in private) or network.prefixlen > 30:
        raise argparse.ArgumentTypeError('Wymagana jest prywatna sieć LAN RFC1918 z adresami hostów.')
    return str(network)


def valid_address(value, school_lan):
    address, network = ipaddress.IPv4Address(value), ipaddress.IPv4Network(school_lan)
    return address in network and address not in (network.network_address, network.broadcast_address)


class InstallError(RuntimeError):
    pass


def run(command, *, data=None, timeout=300):
    result = subprocess.run(command, input=data, capture_output=True, timeout=timeout)
    if result.returncode:
        # No input data, passwords, or environment values are printed.
        error = result.stderr.decode(errors="replace")[:1800]
        raise InstallError(f"Polecenie {command[0]} nie powiodło się: {error}")
    return result.stdout.decode()


def api(path, *options):
    return json.loads(run(["pvesh", "get", path, *options, "--output-format", "json"], timeout=30))


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def download(url, output):
    if not url.startswith("https://"):
        raise InstallError("Pobieranie wymaga HTTPS.")
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Plik już istnieje: {output}")
    descriptor, name = tempfile.mkstemp(prefix=output.name + ".partial-", dir=output.parent)
    os.close(descriptor)
    partial = Path(name)
    try:
        run(["curl", "--ipv4", "--fail", "--silent", "--show-error", "--location",
             "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "20",
             "--max-time", "1800", "--retry", "2", "--retry-delay", "2",
             "--retry-max-time", "1800", "--retry-all-errors", "--output", str(partial),
             "--url", url], timeout=3700)
        # Publish atomically and refuse a destination created by another process.
        os.link(partial, output)
    finally:
        partial.unlink(missing_ok=True)


def image_checksum(manifest):
    for line in manifest.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == IMAGE_NAME and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise InstallError("Brak sumy właściwego obrazu w oficjalnym SHA256SUMS.")


def preflight(resources, status, storage, networks):
    if VMID in PROTECTED or any(int(item["vmid"]) == VMID for item in resources):
        raise InstallError("VMID 104 jest zajęty (VM lub kontener). Nie zmieniono istniejącego gościa.")
    pool = next((item for item in storage if item["storage"] == STORAGE), None)
    if not pool or not pool.get("active") or pool.get("type") != "zfspool" or "images" not in pool.get("content", ""):
        raise InstallError("Brak aktywnego local-zfs z obsługą obrazów dysków.")
    if pool.get("avail", 0) < 50 * GIB:
        raise InstallError("Potrzeba co najmniej 50 GiB wolnego storage na dysk 40 GiB i rezerwę.")
    if not any(item.get("iface") == BRIDGE and item.get("type") == "bridge" and item.get("active") for item in networks):
        raise InstallError("Brak aktywnego mostu vmbr0.")
    configured = sum(int(item.get("maxmem", 0)) for item in resources
                     if item.get("node") == NODE and item.get("status") == "running")
    memory = status["memory"]
    if memory["total"] - configured - 2 * GIB < 3 * GIB or memory["free"] < 6 * GIB:
        raise InstallError("Przydział 2 GiB nie pozostawia wymaganej rezerwy RAM; nie zmieniono innych VM.")
    if status.get("cpuinfo", {}).get("cpus", os.cpu_count() or 1) < 2:
        raise InstallError("Host nie udostępnia dwóch CPU wymaganych przez ten profil.")


def guest_exec(command, *, data=None, timeout=60):
    args = ["qm", "guest", "exec", str(VMID), "--synchronous", "1", "--timeout", str(timeout)]
    if data is not None:
        args += ["--pass-stdin", "1"]
    result = json.loads(run(args + ["--"] + command, data=data, timeout=timeout + 20))
    if not result.get("exited") or result.get("exitcode") != 0:
        raise InstallError("Polecenie w nowej VM nie powiodło się: " + result.get("err-data", "")[:1200])
    return result.get("out-data", "")


def guest_config(source, public_keys=None, school_lan=SCHOOL_LAN):
    # These files contain public source code/settings only. Passwords are entered later.
    if public_keys is not None and (not isinstance(public_keys, list) or any(not isinstance(key, str) for key in public_keys)):
        raise ValueError("Publiczne klucze SSH muszą być listą wpisów.")
    school_lan = school_network(school_lan)
    firewall = r'''#!/bin/bash
set -euo pipefail
iface=$(ip -4 route show default | awk 'NR==1 {print $5}')
test -n "$iface"
iptables -w -n -L DOCKER-USER >/dev/null 2>&1 || iptables -w -N DOCKER-USER
# Replace this installer's chain as one ruleset; do not temporarily empty it.
iptables-restore --wait --noflush <<'RMM_IPV4'
*filter
:SCHOOL_RMM_WEB - [0:0]
-A SCHOOL_RMM_WEB -s @SCHOOL_LAN@ -j RETURN
-A SCHOOL_RMM_WEB -j DROP
COMMIT
RMM_IPV4
iptables -w -C DOCKER-USER -i "$iface" -p tcp --dport 8443 -j SCHOOL_RMM_WEB 2>/dev/null || \
    iptables -w -I DOCKER-USER 1 -i "$iface" -p tcp --dport 8443 -j SCHOOL_RMM_WEB
iptables -w -C INPUT -i "$iface" -p tcp --dport 22 -j SCHOOL_RMM_WEB 2>/dev/null || \
    iptables -w -I INPUT 1 -i "$iface" -p tcp --dport 22 -j SCHOOL_RMM_WEB
# This deployment uses an IPv4-only LAN. Do not leave an IPv6 management path.
if [ -r /proc/sys/net/ipv6/conf/all/disable_ipv6 ] && [ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6)" = 0 ]; then
    ip6tables-restore --wait --noflush <<'RMM_IPV6'
*filter
:SCHOOL_RMM_WEB6 - [0:0]
-A SCHOOL_RMM_WEB6 -j DROP
COMMIT
RMM_IPV6
    for port in 22 443; do
        ip6tables -w -C INPUT -i "$iface" -p tcp --dport "$port" -j SCHOOL_RMM_WEB6 2>/dev/null || \
            ip6tables -w -I INPUT 1 -i "$iface" -p tcp --dport "$port" -j SCHOOL_RMM_WEB6
    done
    if ip6tables -w -n -L DOCKER-USER >/dev/null 2>&1; then
        ip6tables -w -C DOCKER-USER -i "$iface" -p tcp --dport 8443 -j SCHOOL_RMM_WEB6 2>/dev/null || \
            ip6tables -w -I DOCKER-USER 1 -i "$iface" -p tcp --dport 8443 -j SCHOOL_RMM_WEB6
    fi
fi
'''.replace("@SCHOOL_LAN@", school_lan)
    unit = '''[Unit]
Description=School RMM HTTPS access restriction
Wants=network-online.target
After=network-online.target
Before=docker.service
PartOf=docker.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/school-rmm-firewall
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
'''
    docker_dependency = '''[Unit]
Requires=school-rmm-firewall.service
After=school-rmm-firewall.service
'''
    bootstrap = r'''#!/bin/bash
set -euo pipefail
umask 077
exec > >(tee -a /var/log/school-rmm-install.log) 2>&1
exec 9>/run/lock/school-rmm-firstboot.lock
flock -n 9 || { echo 'Instalacja już trwa w tej VM.'; exit 1; }
systemctl daemon-reload
systemctl enable --now school-rmm-firewall.service
/usr/local/sbin/school-rmm-firewall
systemctl enable --now qemu-guest-agent docker
iface=$(ip -4 route show default | awk 'NR==1 {print $5}')
address=$(ip -4 -o addr show dev "$iface" scope global | awk 'NR==1 {split($4,a,"/"); print a[1]}')
python3 - "$address" <<'PY_NETWORK'
import ipaddress, sys
network = ipaddress.IPv4Network('@SCHOOL_LAN@')
address = ipaddress.IPv4Address(sys.argv[1])
if address not in network or address in (network.network_address, network.broadcast_address):
    raise SystemExit('Adres DHCP poza dozwolonym LAN: ' + str(address))
PY_NETWORK
python3 -c @SOURCE_SETUP@ /var/lib/school-rmm/source.tar.gz /opt/school-rmm @SOURCE_SHA@
cd /opt/school-rmm
python3 deploy/init_deployment.py --hostname "$address" --bind-address "$address"
export DOCKER_BUILDKIT=1
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d --no-build --wait --wait-timeout 180
docker compose -f deploy/compose.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt ./school-rmm-ca.crt
curl --fail --silent --show-error --noproxy '*' --cacert school-rmm-ca.crt "https://$address/healthz/"
python3 - "$address" <<'PY_STATUS'
import json, sys
from pathlib import Path
Path('/var/lib/school-rmm-install.ready').write_text(json.dumps({
    'ip': sys.argv[1], 'url': 'https://' + sys.argv[1] + '/', 'revision': '@REVISION@'
}))
PY_STATUS
'''.replace("@SOURCE_SHA@", SOURCE_SHA256).replace("@REVISION@", REVISION).replace("@SCHOOL_LAN@", school_lan).replace("@SOURCE_SETUP@", shlex.quote(SOURCE_SETUP))
    return {
        "hostname": "school-rmm", "manage_etc_hosts": True,
        "disable_root": True, "ssh_pwauth": False,
        "users": [{"name": "rmmadmin", "lock_passwd": True, "shell": "/bin/bash",
                   "sudo": ["ALL=(ALL) NOPASSWD:ALL"], "ssh_authorized_keys": public_keys or []}],
        "package_update": True, "package_upgrade": False,
        "packages": ["qemu-guest-agent", "docker.io", "docker-compose-v2", "docker-buildx", "python3", "curl", "ca-certificates", "iptables"],
        "write_files": [
            {"path": "/var/lib/school-rmm/source.tar.gz", "encoding": "b64", "permissions": "0600", "content": base64.b64encode(source).decode()},
            {"path": "/usr/local/sbin/school-rmm-firstboot", "permissions": "0700", "content": bootstrap},
            {"path": "/usr/local/sbin/school-rmm-firewall", "permissions": "0700", "content": firewall},
            {"path": "/etc/systemd/system/school-rmm-firewall.service", "permissions": "0644", "content": unit},
            {"path": "/etc/systemd/system/docker.service.d/school-rmm-firewall.conf", "permissions": "0644", "content": docker_dependency},
            {"path": "/etc/apt/apt.conf.d/99-school-rmm-ipv4", "permissions": "0644", "content": 'Acquire::ForceIPv4 "true";\n'},
        ],
        "runcmd": [["bash", "/usr/local/sbin/school-rmm-firstboot"]],
    }


def create_vm(work, source, image, public_keys=None, school_lan=SCHOOL_LAN):
    snippet_root = SNIPPET_ROOT
    if snippet_root.exists() or SNIPPET_STORAGE in {item["storage"] for item in api("/storage")}:
        raise InstallError("Miejsce na konfigurację cloud-init już istnieje. Przerwano bez nadpisywania.")
    snippet_root.mkdir(mode=0o755)
    (snippet_root / "snippets").mkdir(mode=0o755)
    user_data = snippet_root / "snippets" / "school-rmm-104.yaml"
    with user_data.open("x") as stream:
        stream.write("#cloud-config\n" + json.dumps(guest_config(source, public_keys, school_lan), indent=2))
    user_data.chmod(0o644)
    run(["pvesm", "add", "dir", SNIPPET_STORAGE, "--path", str(snippet_root), "--content", "snippets", "--nodes", NODE])
    marker = "school-rmm-installer:" + uuid.uuid4().hex
    run(["qm", "create", str(VMID), "--name", "school-rmm", "--memory", "2048", "--balloon", "0",
         "--cores", "2", "--cpu", "host", "--ostype", "l26", "--scsihw", "virtio-scsi-single",
         "--net0", f"virtio,bridge={BRIDGE}", "--agent", "enabled=1", "--onboot", "1",
         "--serial0", "socket", "--vga", "serial0", "--tags", "school-rmm", "--description", marker])
    state = {"marker": marker, "vmid": VMID, "work": str(work), "school_lan": school_lan}
    with (STATE_DIR / "104.json").open("x") as stream:
        json.dump(state, stream)
    print("Importuję zweryfikowany obraz do nowej VM 104...", flush=True)
    run(["qm", "importdisk", str(VMID), str(image), STORAGE, "--format", "raw"], timeout=900)
    config = api(f"/nodes/{NODE}/qemu/{VMID}/config")
    disks = [value.split(",")[0] for key, value in config.items() if re.fullmatch(r"unused\d+", key)]
    if len(disks) != 1 or not disks[0].startswith(f"{STORAGE}:vm-{VMID}-"):
        raise InstallError("Nie udało się jednoznacznie ustalić dysku nowej VM. Nie zgaduję nazwy wolumenu.")
    run(["qm", "set", str(VMID), "--scsi0", disks[0] + ",discard=on,ssd=1", "--ide2", f"{STORAGE}:cloudinit",
         "--boot", "order=scsi0", "--ipconfig0", "ip=dhcp", "--cicustom", f"user={SNIPPET_STORAGE}:snippets/school-rmm-104.yaml"])
    run(["qm", "resize", str(VMID), "scsi0", "40G"])
    run(["qm", "snapshot", str(VMID), "clean-os", "--description", "Zweryfikowany system przed pierwszym startem School RMM"])
    run(["qm", "start", str(VMID)])
    return state


def owned_state():
    state = json.loads((STATE_DIR / "104.json").read_text())
    config = api(f"/nodes/{NODE}/qemu/{VMID}/config")
    if (state.get("vmid") != VMID or not re.fullmatch(r"school-rmm-installer:[0-9a-f]{32}", state.get("marker", ""))
            or config.get("description") != state["marker"] or config.get("name") != "school-rmm"):
        raise InstallError("VM 104 nie jest jednoznacznie własnością tego instalatora.")
    work = Path(state["work"])
    if work.is_symlink() or not work.is_dir() or work.parent.resolve() != STATE_DIR.resolve():
        raise InstallError("Nieprawidłowy katalog stanu istniejącej instalacji.")
    return state


def save_state(state):
    temporary = STATE_DIR / ("104.json." + uuid.uuid4().hex)
    with temporary.open("x") as stream:
        json.dump(state, stream)
    temporary.replace(STATE_DIR / "104.json")


def resume_vm(state, school_lan):
    """Repair only our VM, after a read-only check and a snapshot of its disk."""
    if owned_state() != state:
        raise InstallError("Stan instalacji zmienił się; przerwano wznowienie.")
    if api(f"/nodes/{NODE}/qemu/{VMID}/status/current").get("status") != "running":
        raise InstallError("VM 104 musi działać, aby odczytać stan przez agenta QEMU.")
    check = r'''
import ipaddress, json, subprocess, sys
from pathlib import Path
d = json.load(sys.stdin)
p = subprocess.run(['cloud-init', 'status', '--format', 'json'], capture_output=True, text=True)
try:
    status = json.loads(p.stdout)['status']
except (ValueError, KeyError):
    raise SystemExit('Nie można potwierdzić zakończenia cloud-init.')
if status not in ('done', 'error', 'disabled'):
    raise SystemExit('Cloud-init jeszcze pracuje; pozostaw instalację uruchomioną.')
if d.get('resume_unit'):
    previous = subprocess.run(['systemctl', 'is-active', d['resume_unit']], capture_output=True, text=True).stdout.strip()
    if previous in ('activating', 'active', 'reloading'):
        raise SystemExit('Poprzednie wznowienie jeszcze działa; użyj --finish.')
routes = json.loads(subprocess.check_output(['ip', '-j', '-4', 'route', 'show', 'default']))
addresses = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr', 'show', 'dev', routes[0]['dev'], 'scope', 'global']))
address = ipaddress.IPv4Address(addresses[0]['addr_info'][0]['local'])
network = ipaddress.IPv4Network(d['school_lan'])
if address not in network or address in (network.network_address, network.broadcast_address):
    raise SystemExit('Adres VM poza wskazanym LAN: ' + str(address))
if not Path('/opt/school-rmm').is_dir():
    raise SystemExit('Brak wcześniej wypakowanych źródeł; wymagane sprawdzenie przed wznowieniem.')
subprocess.run([sys.executable, '-c', d['source_setup'], '/var/lib/school-rmm/source.tar.gz', '/opt/school-rmm', d['source_sha']], check=True)
print('Adres VM:', address, 'Dozwolony LAN:', network)
'''
    print(guest_exec(["python3", "-c", check], data=json.dumps({
        "school_lan": school_lan, "resume_unit": state.get("resume_unit"),
        "source_setup": SOURCE_SETUP, "source_sha": SOURCE_SHA256,
    }).encode(), timeout=60).strip(), flush=True)
    attempt = uuid.uuid4().hex[:12]
    print("Tworzę snapshot VM 104 przed wznowieniem; zachowuję istniejący dysk i dane...", flush=True)
    run(["qm", "snapshot", str(VMID), "before-resume-" + attempt,
         "--description", "Stan przed poprawką LAN School RMM"], timeout=180)
    files = [item for item in guest_config(b"", school_lan=school_lan)["write_files"]
             if item["path"] != "/var/lib/school-rmm/source.tar.gz"]
    repair = r'''
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
d = json.load(sys.stdin)
backup = Path('/var/backups/school-rmm') / d['attempt']
for item in d['files']:
    path = Path(item['path'])
    if path.is_symlink() or (path.exists() and not path.is_file()) or any(parent.is_symlink() for parent in path.parents):
        raise SystemExit('Niestandardowa ścieżka instalatora; zachowano pliki: ' + str(path))
backup.mkdir(mode=0o700, parents=True)
for item in d['files']:
    path = Path(item['path'])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        destination = backup / path.relative_to('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    with os.fdopen(descriptor, 'w') as output:
        output.write(item['content'])
    os.chmod(name, int(item['permissions'], 8))
    os.replace(name, path)
subprocess.run(['/usr/local/sbin/school-rmm-firewall'], check=True)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
# A previous ready file must not report success while the repair is still running.
ready = Path('/var/lib/school-rmm-install.ready')
if ready.exists():
    ready.rename(backup / 'previous-ready.json')
subprocess.run(['systemd-run', '--no-block', '--unit', d['unit'], '--property=Type=oneshot',
                '--property=RemainAfterExit=yes', '/usr/local/sbin/school-rmm-firstboot'], check=True)
print('Wznowiono instalację. Kopia plików instalatora:', backup)
'''
    state.update({"school_lan": school_lan, "resume_unit": "school-rmm-resume-" + attempt + ".service"})
    save_state(state)
    print(guest_exec(["python3", "-c", repair], data=json.dumps({
        "files": files, "attempt": attempt, "unit": state["resume_unit"],
    }).encode(), timeout=90).strip(), flush=True)
    return state


def installation_failure(resume_unit=None):
    """Read first-boot outcome without treating cloud-init's error exit as an RPC error."""
    code = (
        "import json,subprocess; from pathlib import Path; "
        "p=subprocess.run(['cloud-init','status','--format','json'], capture_output=True, text=True); "
        "log=Path('/var/log/school-rmm-install.log'); "
        "print(json.dumps({'returncode':p.returncode, 'status':p.stdout[-1500:], "
        "'log':log.read_text(errors='replace')[-3000:] if log.exists() else 'Brak logu instalacji'}))"
    )
    if resume_unit:
        code = (
            "import json,subprocess,sys; from pathlib import Path; "
            "p=subprocess.run(['systemctl','show',sys.argv[1],'-p','LoadState','-p','ActiveState','-p','Result'], capture_output=True, text=True); "
            "log=Path('/var/log/school-rmm-install.log'); "
            "fields=dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line); "
            "failed=fields.get('LoadState')!='loaded' or fields.get('ActiveState')=='failed' or fields.get('Result','success')!='success'; "
            "print(json.dumps({'returncode':1 if failed else 0, 'status':p.stdout, "
            "'log':log.read_text(errors='replace')[-3000:] if log.exists() else 'Brak logu instalacji'}))"
        )
    try:
        report = json.loads(guest_exec(["python3", "-c", code] + ([resume_unit] if resume_unit else []), timeout=15))
    except (InstallError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None
    if report.get("returncode") == 1:
        return report.get("log") or report.get("status") or "Cloud-init zgłosił błąd."
    return None


def wait_ready(school_lan=SCHOOL_LAN, resume_unit=None):
    print("Czekam na DHCP, instalację pakietów i uruchomienie HTTPS (do 25 minut)...", flush=True)
    deadline = time.monotonic() + 25 * 60
    while time.monotonic() < deadline:
        try:
            status = json.loads(guest_exec(["cat", "/var/lib/school-rmm-install.ready"], timeout=15))
            address = ipaddress.IPv4Address(status["ip"])
            if (not valid_address(str(address), school_lan) or status["revision"] != REVISION
                    or status.get("url") != f"https://{address}/"):
                raise InstallError("Nieoczekiwany raport gotowości VM.")
            return status
        except (InstallError, json.JSONDecodeError, subprocess.TimeoutExpired):
            failure = installation_failure(resume_unit)
            if failure:
                raise InstallError("Instalacja wewnątrz VM zakończyła się błędem; zachowano VM i dysk.\n" + failure)
            print(".", end="", flush=True)
            time.sleep(10)
    raise InstallError("Upłynął czas instalacji. VM zachowano. Odczytaj /var/log/school-rmm-install.log przez qm guest exec 104.")


def bootstrap_admin():
    existing = guest_exec(["docker", "compose", "-f", "/opt/school-rmm/deploy/compose.yaml", "exec", "-T", "app",
                          "python", "manage.py", "shell", "-c",
                          "from django.contrib.auth.models import User; print('RMM_ADMIN_EXISTS' if User.objects.filter(is_superuser=True,is_active=True).exists() else 'RMM_ADMIN_NEEDED')"], timeout=60)
    if "RMM_ADMIN_EXISTS" in existing.splitlines():
        print("Zachowano istniejące konto administratora i jego hasło.")
        return
    print("\nUstaw imienne konto aplikacji. Hasło nie będzie wyświetlone ani zapisane w pliku.", flush=True)
    username = input("Login administratora [maciejnajwer]: ").strip() or "maciejnajwer"
    if not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,150}", username):
        raise InstallError("Nieprawidłowa nazwa konta.")
    password = getpass.getpass("Hasło (co najmniej 14 znaków): ")
    if password != getpass.getpass("Powtórz hasło: "):
        raise InstallError("Hasła nie są takie same. VM pozostaje uruchomiona; użyj --finish, aby dokończyć.")
    code = (
        "import json,sys; from django.contrib.auth.models import User; "
        "from django.contrib.auth.password_validation import validate_password; "
        "d=json.load(sys.stdin); "
        "u=User(username=d['username'], is_staff=True, is_superuser=True); "
        "validate_password(d['password'], u); u.set_password(d['password']); u.full_clean(); u.save(); "
        "print('Konto utworzone. Pierwsze logowanie wymaga skonfigurowania TOTP.')"
    )
    output = guest_exec(["docker", "compose", "-f", "/opt/school-rmm/deploy/compose.yaml", "exec", "-T", "app",
                        "python", "manage.py", "shell", "-c", code],
                       data=json.dumps({"username": username, "password": password}).encode(), timeout=90)
    print(output.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--finish", action="store_true", help="Finish this installer's existing VM; never recreates disks.")
    mode.add_argument("--resume", action="store_true", help="Resume a failed installation on the owned VM 104, preserving disks and data.")
    parser.add_argument("--school-lan", required=True, type=school_network,
                        help="Explicit school LAN CIDR, e.g. 192.168.16.0/22. Do not infer it from the pve address.")
    args = parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname().split(".")[0] != NODE:
        raise InstallError("Uruchom na hoście pve w istniejącej sesji root@pve.")
    for binary in ("qm", "pvesh", "pvesm", "qemu-img", "curl"):
        if not shutil.which(binary):
            raise InstallError("Brak wymaganego narzędzia: " + binary)
    os.umask(0o077)
    lock = open("/run/lock/school-rmm-provision-104.lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if "--pass-stdin" not in run(["qm", "help", "guest", "exec"], timeout=30):
        raise InstallError("Zainstalowany qm nie deklaruje --pass-stdin; przerwano przed zmianami.")
    if args.finish or args.resume:
        state = owned_state()
        if args.resume:
            state = resume_vm(state, args.school_lan)
        elif state.get("school_lan") != args.school_lan:
            raise InstallError("Konfiguracja LAN wymaga --resume; --finish nie zmienia zapory istniejącej VM.")
        work = Path(state["work"])
    else:
        resources = api("/cluster/resources", "--type", "vm")
        status = api(f"/nodes/{NODE}/status")
        storage = api(f"/nodes/{NODE}/storage")
        networks = api(f"/nodes/{NODE}/network")
        preflight(resources, status, storage, networks)
        STATE_DIR.mkdir(mode=0o700, exist_ok=True)
        if (STATE_DIR / "104.json").exists():
            raise InstallError("Istnieje stan wcześniejszej instalacji; wymagane sprawdzenie, nie nadpisanie.")
        work = Path(tempfile.mkdtemp(prefix="104-", dir=STATE_DIR))
        (work / "before.json").write_text(json.dumps({"vms": resources, "host": status, "storage": storage, "network": networks}, indent=2))
        print("Nowa VM 104: 2 vCPU, 2 GiB RAM, 40 GiB local-zfs, vmbr0/DHCP. Chronione: 100, 101, 103.", flush=True)
        print("Pobieram system Ubuntu i sprawdzam SHA256 z oficjalnego HTTPS...", flush=True)
        sums = work / "SHA256SUMS"
        image = work / IMAGE_NAME
        source = work / "school-rmm.tar.gz"
        download(IMAGE_BASE + "SHA256SUMS", sums)
        expected = image_checksum(sums.read_text())
        download(IMAGE_BASE + IMAGE_NAME, image)
        if digest(image) != expected:
            raise InstallError("Obraz nie przeszedł SHA256. Nie utworzono VM; nie zmieniaj oczekiwanej sumy.")
        info = json.loads(run(["qemu-img", "info", "--output=json", str(image)]))
        if info["format"] != "qcow2" or info.get("backing-filename") or info["virtual-size"] > 40 * GIB:
            raise InstallError("Nieoczekiwany format lub rozmiar obrazu.")
        download(SOURCE_URL, source)
        if digest(source) != SOURCE_SHA256:
            raise InstallError("Archiwum aplikacji nie przeszło kontroli SHA256.")
        # Public authorized keys only, never a private key or an SSH password.
        authorized_keys = Path("/root/.ssh/authorized_keys")
        public_keys = []
        if authorized_keys.is_file():
            public_keys = [line.strip() for line in authorized_keys.read_text().splitlines()
                           if line.strip() and not line.lstrip().startswith("#")]
        state = create_vm(work, source.read_bytes(), image, public_keys, args.school_lan)
    status = wait_ready(args.school_lan, state.get("resume_unit"))
    ca_path = work / "school-rmm-ca.crt"
    ca_path.write_text(guest_exec(["cat", "/opt/school-rmm/school-rmm-ca.crt"]))
    # pve's management subnet need not belong to the school client LAN. Probe
    # through QGA inside the guest; do not create a firewall exception for pve.
    response = guest_exec(["curl", "--fail", "--silent", "--show-error", "--noproxy", "*",
                           "--max-time", "15", "--cacert", "/opt/school-rmm/school-rmm-ca.crt",
                           "https://" + status["ip"] + "/healthz/"], timeout=30)
    if json.loads(response).get("status") != "ok":
        raise InstallError("HTTPS nie potwierdził gotowości aplikacji.")
    (STATE_DIR / "school-rmm-104-ca.crt").write_text(ca_path.read_text())
    bootstrap_admin()
    print("\nPanel działa: https://" + status["ip"] + "/")
    print("Dozwolony LAN: " + args.school_lan)
    print("Publiczny certyfikat CA do pobrania na Maca przez istniejące SSH: " + str(STATE_DIR / "school-rmm-104-ca.crt"))
    print("Zaufaj temu CA w Pęku kluczy przed otwarciem panelu. Nie wyłączaj weryfikacji TLS.")
    print("Adres pochodzi z DHCP — zarezerwuj go w routerze dla nowej VM. Raport i obraz zachowano: " + str(work))
    print("VM 100, 101 i 103 nie były modyfikowane. Zdalne zarządzanie agentami pozostaje osobnym etapem.")


if __name__ == "__main__":
    try:
        main()
    except (InstallError, OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        print("\nInstalacja zatrzymana: " + str(error), file=sys.stderr)
        print("Nie usuwaj istniejących VM ani danych. Jeśli VM 104 została utworzona, zachowano ją do diagnostyki.", file=sys.stderr)
        sys.exit(1)
