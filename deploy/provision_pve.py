#!/usr/bin/env python3
"""Provision only a new School RMM VM on pve. Run from the owner's SSH terminal."""
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
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
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
SCHOOL_LAN = "192.168.0.0/24"


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
    with urllib.request.urlopen(url, timeout=60) as response, Path(output).open("xb") as stream:
        shutil.copyfileobj(response, stream)


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


def guest_config(source, public_keys=None):
    # These files contain public source code/settings only. Passwords are entered later.
    if public_keys is not None and (not isinstance(public_keys, list) or any(not isinstance(key, str) for key in public_keys)):
        raise ValueError("Publiczne klucze SSH muszą być listą wpisów.")
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
'''.replace("@SCHOOL_LAN@", SCHOOL_LAN)
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
systemctl daemon-reload
systemctl enable --now school-rmm-firewall.service
systemctl enable --now qemu-guest-agent docker
printf '%s  %s\n' '@SOURCE_SHA@' /var/lib/school-rmm/source.tar.gz | sha256sum --check -
test ! -e /opt/school-rmm
install -d -m 0755 /opt/school-rmm
tar --extract --gzip --file /var/lib/school-rmm/source.tar.gz --strip-components=1 --directory /opt/school-rmm
iface=$(ip -4 route show default | awk 'NR==1 {print $5}')
address=$(ip -4 -o addr show dev "$iface" scope global | awk 'NR==1 {split($4,a,"/"); print a[1]}')
case "$address" in 192.168.0.*) ;; *) printf 'Nieoczekiwana sieć DHCP: %s\n' "$address"; exit 1;; esac
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
'''.replace("@SOURCE_SHA@", SOURCE_SHA256).replace("@REVISION@", REVISION)
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
        ],
        "runcmd": [["bash", "/usr/local/sbin/school-rmm-firstboot"]],
    }


def create_vm(work, source, image, public_keys=None):
    snippet_root = SNIPPET_ROOT
    if snippet_root.exists() or SNIPPET_STORAGE in {item["storage"] for item in api("/storage")}:
        raise InstallError("Miejsce na konfigurację cloud-init już istnieje. Przerwano bez nadpisywania.")
    snippet_root.mkdir(mode=0o755)
    (snippet_root / "snippets").mkdir(mode=0o755)
    user_data = snippet_root / "snippets" / "school-rmm-104.yaml"
    with user_data.open("x") as stream:
        stream.write("#cloud-config\n" + json.dumps(guest_config(source, public_keys), indent=2))
    user_data.chmod(0o644)
    run(["pvesm", "add", "dir", SNIPPET_STORAGE, "--path", str(snippet_root), "--content", "snippets", "--nodes", NODE])
    marker = "school-rmm-installer:" + uuid.uuid4().hex
    run(["qm", "create", str(VMID), "--name", "school-rmm", "--memory", "2048", "--balloon", "0",
         "--cores", "2", "--cpu", "host", "--ostype", "l26", "--scsihw", "virtio-scsi-single",
         "--net0", f"virtio,bridge={BRIDGE}", "--agent", "enabled=1", "--onboot", "1",
         "--serial0", "socket", "--vga", "serial0", "--tags", "school-rmm", "--description", marker])
    state = {"marker": marker, "vmid": VMID, "work": str(work)}
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


def wait_ready():
    print("Czekam na DHCP, instalację pakietów i uruchomienie HTTPS (do 25 minut)...", flush=True)
    deadline = time.monotonic() + 25 * 60
    while time.monotonic() < deadline:
        try:
            status = json.loads(guest_exec(["cat", "/var/lib/school-rmm-install.ready"], timeout=15))
            address = ipaddress.IPv4Address(status["ip"])
            if address not in ipaddress.IPv4Network("192.168.0.0/24") or str(address) in {"192.168.0.0", "192.168.0.250", "192.168.0.255"} or status["revision"] != REVISION:
                raise InstallError("Nieoczekiwany raport gotowości VM.")
            return status
        except (InstallError, json.JSONDecodeError, subprocess.TimeoutExpired):
            print(".", end="", flush=True)
            time.sleep(10)
    raise InstallError("Upłynął czas instalacji. VM zachowano. Odczytaj /var/log/school-rmm-install.log przez qm guest exec 104.")


def bootstrap_admin():
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
    parser.add_argument("--finish", action="store_true", help="Finish this installer's existing VM; never recreates disks.")
    args = parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname().split(".")[0] != NODE:
        raise InstallError("Uruchom na hoście pve w istniejącej sesji root@pve.")
    for binary in ("qm", "pvesh", "pvesm", "qemu-img"):
        if not shutil.which(binary):
            raise InstallError("Brak wymaganego narzędzia: " + binary)
    os.umask(0o077)
    lock = open("/run/lock/school-rmm-provision-104.lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if "--pass-stdin" not in run(["qm", "help", "guest", "exec"], timeout=30):
        raise InstallError("Zainstalowany qm nie deklaruje --pass-stdin; przerwano przed zmianami.")
    if args.finish:
        state = json.loads((STATE_DIR / "104.json").read_text())
        config = api(f"/nodes/{NODE}/qemu/{VMID}/config")
        if state["vmid"] != VMID or config.get("description") != state["marker"]:
            raise InstallError("VM 104 nie jest jednoznacznie własnością tego instalatora.")
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
        create_vm(work, source.read_bytes(), image, public_keys)
    status = wait_ready()
    ca_path = work / "school-rmm-ca.crt"
    ca_path.write_text(guest_exec(["cat", "/opt/school-rmm/school-rmm-ca.crt"]))
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ca_path))))
    with client.open("https://" + status["ip"] + "/healthz/", timeout=15) as response:
        if json.load(response).get("status") != "ok":
            raise InstallError("HTTPS nie potwierdził gotowości aplikacji.")
    bootstrap_admin()
    print("\nPanel działa: https://" + status["ip"] + "/")
    print("Publiczny certyfikat CA do pobrania na Maca przez istniejące SSH: " + str(ca_path))
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
