"""Run on the authorized Proxmox host. Reads state only; never changes guests."""
import json
import os
import shutil
import socket
import subprocess

PROTECTED_VMIDS = {100, 101, 103}


def read_api(path, *options):
    result = subprocess.run(["pvesh", "get", path, *options, "--output-format", "json"],
                            check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


def selected(record, fields):
    return {field: record[field] for field in fields if field in record}


def main():
    if os.geteuid() != 0 or not shutil.which("pvesh"):
        raise SystemExit("Uruchom na upoważnionym hoście Proxmox jako root. Nie wykonano zmian.")
    node = socket.gethostname().split(".")[0]
    if node != "pve":
        raise SystemExit("Oczekiwano hosta pve. Przerwano bez zmian.")
    resources = read_api("/cluster/resources", "--type", "vm")
    vm_fields = ["vmid", "name", "node", "type", "status", "maxmem", "mem", "maxcpu", "maxdisk"]
    vms = [selected(item, vm_fields) for item in resources]
    host = read_api(f"/nodes/{node}/status")
    storage = read_api(f"/nodes/{node}/storage")
    network = read_api(f"/nodes/{node}/network")
    report = {
        "read_only": True, "node": node,
        "host": selected(host, ["cpu", "cpuinfo", "memory", "rootfs", "uptime"]),
        "vms": vms,
        "protected_vmids": sorted(PROTECTED_VMIDS),
        "protected_vms": [item for item in vms if int(item.get("vmid", -1)) in PROTECTED_VMIDS],
        "missing_protected_vmids": sorted(PROTECTED_VMIDS - {int(item["vmid"]) for item in vms}),
        "next_free_vmid": read_api("/cluster/nextid"),
        "storage": [selected(item, ["storage", "type", "total", "used", "avail", "content", "active", "enabled", "shared"]) for item in storage],
        "network": [selected(item, ["iface", "type", "address", "netmask", "gateway", "bridge_ports", "active", "autostart"]) for item in network],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
