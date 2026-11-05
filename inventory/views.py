import csv
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from .domain import POLICIES, SUPPORT_LABELS
from .forms import DeviceForm
from .models import AuditEvent, Device, Room


def visible_rooms(user):
    rooms = Room.objects.select_related("school")
    if user.is_superuser:
        return rooms
    return rooms.filter(school__membership__user=user,
                        school__membership__role__in=["admin", "technician"]).distinct()


def visible_devices(user):
    if not user.is_superuser and not user.membership_set.filter(role__in=["admin", "technician"]).exists():
        raise PermissionDenied("Brak uprawnień do ewidencji. Panel nauczyciela powstanie w osobnym etapie.")
    return Device.objects.select_related("room__school").filter(room__in=visible_rooms(user))


def filtered_devices(request):
    queryset = visible_devices(request.user)
    for param, field in [("school", "room__school_id"), ("room", "room_id"),
                         ("os_version", "os_version"), ("os_edition", "os_edition")]:
        value = request.GET.get(param, "")
        if value and (param not in ("school", "room") or value.isdigit()):
            queryset = queryset.filter(**{field: value})
    if request.GET.get("q"):
        queryset = queryset.filter(name__icontains=request.GET["q"][:120])
    policy_key = request.GET.get("policy", "inventory")
    if policy_key not in POLICIES:
        policy_key = "inventory"
    items = []
    for device in queryset:
        device.policy_result = device.preview(policy_key)
        if request.GET.get("support_status") and request.GET["support_status"] != device.support_status:
            continue
        if request.GET.get("compliance") and request.GET["compliance"] != device.policy_result["status"]:
            continue
        items.append(device)
    return items, policy_key


@login_required
@require_GET
def devices(request):
    items, policy = filtered_devices(request)
    return render(request, "inventory/devices.html", {
        "devices": items, "rooms": visible_rooms(request.user).order_by("school__name", "name"),
        "policies": POLICIES, "policy": policy, "support_labels": SUPPORT_LABELS,
        "count": len(items), "at_risk": sum(d.support_status == "at_risk" for d in items),
        "unverified": sum(d.support_status == "unknown" for d in items),
    })


@login_required
@require_GET
def device_detail(request, pk):
    device = get_object_or_404(visible_devices(request.user), pk=pk)
    return render(request, "inventory/device.html", {"device": device,
        "previews": [device.preview(key) for key in POLICIES],
        "events": AuditEvent.objects.filter(school=device.room.school, object_name=device.name).order_by("-created_at")[:20]})


@login_required
@require_http_methods(["GET", "POST"])
def device_create(request):
    visible_devices(request.user)  # Enforce the same role check on every endpoint.
    form = DeviceForm(request.POST or None, rooms=visible_rooms(request.user))
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            device = form.save()
            AuditEvent.objects.create(actor=request.user, school=device.room.school,
                                      action="device.created.manually", object_name=device.name)
        messages.success(request, "Dodano komputer do ewidencji. Połączenie agenta wymaga integracji MeshCentral.")
        return redirect("device-detail", pk=device.pk)
    return render(request, "inventory/form.html", {"form": form})


def serialize_device(device):
    return {"id": device.pk, "name": device.name, "school": device.room.school.name,
            "room": device.room.name, "os_family": device.os_family, "os_version": device.os_version,
            "os_release": device.os_release, "os_edition": device.os_edition, "os_build": device.os_build,
            "support_status": device.support_status, "esu_status": device.esu_status,
            "capabilities": device.capabilities, "policy": device.policy_result,
            "cpu": device.cpu, "ram_gb": device.ram_gb, "disk_gb": device.disk_gb,
            "ip_address": device.ip_address, "is_demo": device.is_demo, "connection_status": "not_connected"}


@login_required
@require_GET
def api_devices(request):
    items, _ = filtered_devices(request)
    return JsonResponse({"count": len(items), "devices": [serialize_device(device) for device in items]})


def csv_cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


@login_required
@require_GET
def export_devices(request):
    items, _ = filtered_devices(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="school-rmm-devices.csv"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Komputer", "Szkoła", "Budynek", "Piętro", "Sala", "Windows", "Edycja", "Wydanie", "Kompilacja", "Wsparcie", "ESU", "Zgodność", "Dane testowe"])
    for d in items:
        writer.writerow([csv_cell(v) for v in [d.name, d.room.school.name, d.room.building, d.room.floor,
            d.room.name, d.os_version, d.os_edition, d.os_release, d.os_build,
            d.support_label, d.get_esu_status_display(), d.policy_result["label"], d.is_demo]])
    return response


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "component": "school-rmm", "meshcentral": "not_connected"})
