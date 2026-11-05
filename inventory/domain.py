"""Conservative capability evaluation; never trusts a capability claim from a device."""
from datetime import date

CAPABILITIES = {
    "inventory": "Ewidencja sprzętu",
    "remote_desktop": "Zdalny pulpit przez agenta",
    "terminal": "Terminal PowerShell",
    "software": "Zarządzanie oprogramowaniem",
    "power": "Restart i wyłączenie",
    "local_group_policy": "Lokalne zasady grupy (Pro)",
    "rdp_host": "Wbudowany serwer RDP (Pro)",
}
SUPPORT_LABELS = {
    "supported": "Wspierany",
    "at_risk": "Zagrożony — Windows 10 bez ESU",
    "unknown": "Wymaga weryfikacji",
    "unsupported": "Poza zakresem wsparcia",
}
POLICIES = {
    "inventory": {"name": "Ewidencja urządzeń", "required": ["inventory"]},
    "classroom_pro": {"name": "Pracownia Pro: ewidencja i lokalne zasady grupy",
                      "required": ["inventory", "local_group_policy"]},
    "remote_support": {"name": "Zdalna pomoc przez agenta",
                       "required": ["remote_desktop", "terminal"]},
}
# Home/Pro servicing dates; ESU is checked separately. Unknown builds fail closed.
WINDOWS_11_END = {"23H2": date(2025, 11, 11), "24H2": date(2026, 10, 13),
                  "25H2": date(2027, 10, 12)}
WINDOWS_11_BUILD = {"23H2": "22631", "24H2": "26100", "25H2": "26200"}


def support_status(device, today=None):
    today = today or date.today()
    if device.os_family != "Windows" or device.os_edition not in ("Home", "Pro"):
        return "unsupported"
    if device.os_version == "10":
        if device.os_release != "22H2" or device.os_build.split(".")[0] != "19045":
            return "unsupported"
        if device.esu_status == "inactive":
            return "at_risk"
        if device.esu_status == "active" and device.esu_valid_until and device.esu_verified_at and device.esu_evidence.strip():
            if device.esu_valid_until < today:
                return "at_risk"
            # Evidence ages: do not treat last year's ESU as a current entitlement.
            if (today - device.esu_verified_at.date()).days in range(0, 31):
                return "supported"
        return "unknown"
    if device.os_version == "11":
        end = WINDOWS_11_END.get(device.os_release)
        build = WINDOWS_11_BUILD.get(device.os_release)
        if not end or device.os_build.split(".")[0] != build:
            return "unknown"
        return "supported" if today <= end else "unsupported"
    return "unsupported"


def capabilities(device):
    results = {}
    for key in CAPABILITIES:
        available = key == "inventory"
        reason = "Dostępne w panelu ewidencji."
        if key in ("local_group_policy", "rdp_host"):
            available = device.os_family == "Windows" and device.os_version in ("10", "11") and device.os_edition == "Pro"
            reason = "Edycja Pro udostępnia tę funkcję; wykonanie wymaga integracji." if available else "Ta funkcja wymaga edycji Windows Pro."
        elif key != "inventory":
            # An OS edition alone cannot establish that an RMM agent is connected.
            reason = "Integracja z agentem MeshCentral nie jest jeszcze podłączona."
        results[key] = {"label": CAPABILITIES[key], "available": available, "reason": reason}
    return results


def policy_preview(device, policy_key):
    policy = POLICIES[policy_key]
    caps = capabilities(device)
    missing = [{"key": key, "reason": caps[key]["reason"]}
               for key in policy["required"] if not caps[key]["available"]]
    count = len(policy["required"])
    status = "compatible" if not missing else "incompatible" if len(missing) == count else "partial"
    return {"key": policy_key, "name": policy["name"], "status": status, "missing": missing,
            "label": {"compatible": "Zgodny", "partial": "Częściowo zgodny", "incompatible": "Niezgodny"}[status],
            "execution_enabled": False}
