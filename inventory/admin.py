from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import User, Group
from .models import School, Room, Membership, Device, AuditEvent


class RestrictedAdminSite(admin.AdminSite):
    site_header = "School RMM — administracja"
    def has_permission(self, request):
        return request.user.is_active and request.user.is_superuser


site = RestrictedAdminSite(name="admin")
site.register(User, UserAdmin)
site.register(Group, GroupAdmin)
for model in [School, Room, Membership]:
    site.register(model)


@admin.register(Device, site=site)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "room", "os_version", "os_edition", "support_status"]
    list_filter = ["os_version", "os_edition", "room__school"]
    search_fields = ["name"]


@admin.register(AuditEvent, site=site)
class AuditAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "school", "action", "object_name"]
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
