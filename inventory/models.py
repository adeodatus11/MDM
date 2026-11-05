from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from .domain import capabilities, policy_preview, support_status, SUPPORT_LABELS


class School(models.Model):
    name = models.CharField("Nazwa szkoły", max_length=160)
    def __str__(self):
        return self.name


class Room(models.Model):
    school = models.ForeignKey(School, on_delete=models.PROTECT)
    building = models.CharField("Budynek", max_length=80)
    floor = models.CharField("Piętro", max_length=40)
    name = models.CharField("Sala", max_length=80)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["school", "building", "floor", "name"], name="unique_room")]
    def __str__(self):
        return f"{self.school} / {self.building} / {self.floor} / {self.name}"


class Membership(models.Model):
    ROLE_CHOICES = [("admin", "Administrator szkoły"), ("technician", "Technik IT"), ("teacher", "Nauczyciel")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "school"], name="unique_membership")]


class Device(models.Model):
    room = models.ForeignKey(Room, on_delete=models.PROTECT)
    name = models.CharField("Nazwa komputera", max_length=120)
    external_id = models.CharField("Identyfikator MeshCentral", max_length=200, blank=True, default="")
    os_family = models.CharField("Rodzina systemu", max_length=24, default="Windows", choices=[("Windows", "Windows")])
    os_version = models.CharField("Windows", max_length=16, choices=[("10", "10"), ("11", "11")])
    os_release = models.CharField("Wydanie (np. 22H2, 25H2)", max_length=16)
    os_edition = models.CharField("Edycja", max_length=24, choices=[("Home", "Home"), ("Pro", "Pro"), ("Unknown", "Nieustalona")])
    os_build = models.CharField("Numer kompilacji", max_length=32)
    esu_status = models.CharField("ESU", max_length=24, default="unknown", choices=[("unknown", "Niepotwierdzony"), ("active", "Aktywny"), ("inactive", "Nieaktywny"), ("not_applicable", "Nie dotyczy")])
    esu_valid_until = models.DateField("ESU ważne do", null=True, blank=True)
    esu_verified_at = models.DateTimeField("Weryfikacja ESU", null=True, blank=True)
    esu_evidence = models.CharField("Źródło potwierdzenia ESU", max_length=240, blank=True)
    cpu = models.CharField("Procesor", max_length=160, blank=True)
    ram_gb = models.PositiveIntegerField("RAM (GB)", null=True, blank=True, validators=[MinValueValidator(1)])
    disk_gb = models.PositiveIntegerField("Dysk (GB)", null=True, blank=True, validators=[MinValueValidator(1)])
    ip_address = models.GenericIPAddressField("Adres IP", null=True, blank=True)
    is_demo = models.BooleanField(default=False, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["room", "name"], name="unique_device_room"),
            models.UniqueConstraint(fields=["external_id"], condition=~models.Q(external_id=""), name="unique_external_id")]
        ordering = ["name"]

    def clean(self):
        if self.os_version == "10" and self.esu_status == "not_applicable":
            raise ValidationError({"esu_status": "Dla Windows 10 należy zweryfikować ESU."})
        if self.os_version == "10" and self.esu_status == "active" and not (
                self.esu_valid_until and self.esu_verified_at and self.esu_evidence.strip()):
            raise ValidationError({"esu_status": "Aktywne ESU wymaga terminu ważności, daty i źródła weryfikacji."})

    @property
    def support_status(self):
        return support_status(self)
    @property
    def support_label(self):
        return SUPPORT_LABELS[self.support_status]
    @property
    def capabilities(self):
        return capabilities(self)
    def preview(self, policy):
        return policy_preview(self, policy)
    def __str__(self):
        return self.name


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    school = models.ForeignKey(School, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    object_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
