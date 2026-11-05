from django import forms
from .models import Device


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["room", "name", "external_id", "os_family", "os_version", "os_release", "os_edition",
                  "os_build", "esu_status", "esu_valid_until", "esu_verified_at", "esu_evidence",
                  "cpu", "ram_gb", "disk_gb", "ip_address"]
        widgets = {"esu_valid_until": forms.DateInput(attrs={"type": "date"}),
                   "esu_verified_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

    def __init__(self, *args, rooms, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = rooms
