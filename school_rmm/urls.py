from inventory.admin import site
from django.contrib.auth import views as auth
from django.conf import settings
from django.urls import include, path
from django.views.generic import RedirectView
from two_factor.urls import urlpatterns as two_factor_urls
from inventory import views

urlpatterns = [
    path("", include(two_factor_urls)),
    path("admin/", site.urls),
    path("login/", RedirectView.as_view(pattern_name="two_factor:login") if settings.REQUIRE_MFA else
         auth.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("healthz/", views.health, name="health"),
    path("", views.devices, name="devices"),
    path("devices/<int:pk>/", views.device_detail, name="device-detail"),
    path("devices/new/", views.device_create, name="device-create"),
    path("reports/devices.csv", views.export_devices, name="device-export"),
    path("api/devices/", views.api_devices, name="api-devices"),
]
