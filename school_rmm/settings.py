import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SCHOOL_RMM_DATA_DIR", BASE_DIR / "var"))
DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
# Local development key persists between starts; production must supply its own.
DEBUG = os.environ.get("SCHOOL_RMM_DEBUG", "false").lower() == "true"
SECRET_KEY = os.environ.get("SCHOOL_RMM_SECRET_KEY")
if os.environ.get("SCHOOL_RMM_SECRET_KEY_FILE"):
    SECRET_KEY = Path(os.environ["SCHOOL_RMM_SECRET_KEY_FILE"]).read_text().strip()
if not SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured
    if not DEBUG:
        raise ImproperlyConfigured("Ustaw SCHOOL_RMM_SECRET_KEY lub włącz lokalny SCHOOL_RMM_DEBUG=true.")
    from django.core.management.utils import get_random_secret_key
    key_file = DATA_DIR / "development.key"
    try:
        with open(key_file, "x", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
            stream.write(get_random_secret_key())
    except FileExistsError:
        pass
    SECRET_KEY = key_file.read_text()

ALLOWED_HOSTS = os.environ.get("SCHOOL_RMM_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
TRUST_PROXY = os.environ.get("SCHOOL_RMM_TRUST_PROXY", "false").lower() == "true"
REQUIRE_MFA = not DEBUG or os.environ.get("SCHOOL_RMM_REQUIRE_MFA", "false").lower() == "true"
if TRUST_PROXY:
    # Enable only when the app port is private and the proxy replaces this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "axes", "django_otp", "django_otp.plugins.otp_totp", "django_otp.plugins.otp_static",
    "inventory", "two_factor",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django_otp.middleware.OTPMiddleware",
    "school_rmm.middleware.RequireMFAMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware", "axes.middleware.AxesMiddleware",
]
ROOT_URLCONF = "school_rmm.urls"
WSGI_APPLICATION = "school_rmm.wsgi.application"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": DATA_DIR / "school-rmm.sqlite3",
                         "OPTIONS": {"timeout": 20}}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "pl"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "devices"
LOGOUT_REDIRECT_URL = "login"
AUTHENTICATION_BACKENDS = ["axes.backends.AxesStandaloneBackend", "django.contrib.auth.backends.ModelBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 14}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_RESET_ON_SUCCESS = True
# Caddy replaces X-Forwarded-For with exactly one client address (no chain).
AXES_IPWARE_PROXY_COUNT = 0
AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR") if TRUST_PROXY else ("REMOTE_ADDR",)
TWO_FACTOR_PATCH_ADMIN = False
TWO_FACTOR_TOTP_ISSUER = "School RMM"
TWO_FACTOR_QR_FACTORY = "qrcode.image.svg.SvgPathImage"
TWO_FACTOR_REMEMBER_COOKIE_AGE = None
OTP_TOTP_THROTTLE_FACTOR = 1
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 3600
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = False
X_FRAME_OPTIONS = "DENY"
