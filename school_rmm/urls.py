from inventory.admin import site
from django.contrib.auth import views as auth
from django.urls import path
from inventory import views

urlpatterns = [
    path("admin/", site.urls),
    path("login/", auth.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("healthz/", views.health, name="health"),
    path("", views.devices, name="devices"),
    path("devices/<int:pk>/", views.device_detail, name="device-detail"),
    path("devices/new/", views.device_create, name="device-create"),
    path("reports/devices.csv", views.export_devices, name="device-export"),
    path("api/devices/", views.api_devices, name="api-devices"),
]
