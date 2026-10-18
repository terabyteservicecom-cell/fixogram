import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ON_LIARA = Path("/usr/src/app").exists()
ON_SERVER = ON_LIARA or os.environ.get("BEHIND_HTTPS") == "True"

for folder in ("database", "media"):
    try:
        (BASE_DIR / folder).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

DEBUG = os.environ.get("DEBUG", "False" if ON_SERVER else "True") == "True"
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or (
    "dev-only-naghsh-secret-key-change-on-liara-9f3a1c"
)
ALLOWED_HOSTS = [
    "fixogram.ir",
    "www.fixogram.ir",
    "tamirneshan.ir",
    "www.tamirneshan.ir",
    "85.198.54.48",
    "127.0.0.1",
    "localhost",
]
ALLOWED_HOSTS.extend(
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "").split(",")
    if host.strip()
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "talent.apps.TalentConfig",
]

MIDDLEWARE = [
    "talent.pwa.InstallHeaders",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "talent.traffic.VisitMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "talent.gate.VisitorGate",
    "talent.gate.SupportGate",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "talent.context.nav",
                "talent.context.seo",
                "talent.context.home_copy",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "database" / "db.sqlite3",
    }
}

# رمز سادهٔ عددی (مثل ۶ رقم یا کمتر تا حداقل ۴) قبول است؛ بدون قوانین پیچیدگی.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 4},
    },
]

LANGUAGE_CODE = "fa"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
IDENTITY_ROOT = BASE_DIR / "private" / "identity"

# عکس/ویدیو روی صندوقچه آروان (S3) — فقط وقتی کلیدها در env باشند
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "fixogram-media").strip()
AWS_S3_ENDPOINT_URL = os.environ.get(
    "AWS_S3_ENDPOINT_URL", "https://s3.ir-central1.arvanstorage.ir"
).strip()
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "ir-central1").strip()
AWS_S3_CUSTOM_DOMAIN = os.environ.get(
    "AWS_S3_CUSTOM_DOMAIN",
    f"{AWS_STORAGE_BUCKET_NAME}.s3.ir-central1.arvanstorage.ir",
).strip()
USE_ARVAN_MEDIA = bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)

if USE_ARVAN_MEDIA:
    INSTALLED_APPS = [*INSTALLED_APPS, "storages"]
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "access_key": AWS_ACCESS_KEY_ID,
                "secret_key": AWS_SECRET_ACCESS_KEY,
                "bucket_name": AWS_STORAGE_BUCKET_NAME,
                "endpoint_url": AWS_S3_ENDPOINT_URL,
                "region_name": AWS_S3_REGION_NAME,
                "custom_domain": AWS_S3_CUSTOM_DOMAIN,
                "default_acl": "public-read",
                "querystring_auth": False,
                "file_overwrite": False,
                "addressing_style": "virtual",
                "signature_version": "s3v4",
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
ACCOUNT_YEAR_PRICE = 100_000
ADMIN_PHONE = os.environ.get("ADMIN_PHONE", "09124770435")
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"

CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "https://85.198.54.48",
    "https://fixogram.ir",
    "https://www.fixogram.ir",
    "https://tamirneshan.ir",
    "https://www.tamirneshan.ir",
]
if ON_LIARA:
    CSRF_TRUSTED_ORIGINS.extend(
        [
            "https://*.liara.run",
            "https://*.liara.ir",
        ]
    )
CSRF_TRUSTED_ORIGINS.extend(
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
)

if ON_SERVER:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    # نام تازه تا کوکی‌های قدیمی host-only با Domain=.fixogram.ir قاطی نشوند
    SESSION_COOKIE_NAME = "fxsession"
    CSRF_COOKIE_NAME = "fxcsrf"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
    # www و بدون www یک کوکی مشترک داشته باشند تا CSRF نشکند
    SESSION_COOKIE_DOMAIN = ".fixogram.ir"
    CSRF_COOKIE_DOMAIN = ".fixogram.ir"
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # same-origin باعث قطع Referer در بعضی مسیرهای CDN/ورود می‌شود و CSRF می‌شکند
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
