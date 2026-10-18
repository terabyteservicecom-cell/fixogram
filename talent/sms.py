import json
import logging
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from talent.models import LoginCode, SmsSetting

logger = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=2)
CODE_COOLDOWN = timedelta(seconds=60)
CODE_ATTEMPTS = 5


class SmsError(Exception):
    pass


class TooSoon(Exception):
    pass


def credentials():
    row = SmsSetting.objects.order_by("pk").first()
    api_key = os.environ.get("KAVENEGAR_API_KEY", "").strip()
    template = os.environ.get("KAVENEGAR_TEMPLATE", "").strip()
    if row is not None:
        api_key = api_key or row.api_key.strip()
        template = template or row.template.strip()
    return api_key, template


def _kavenegar(api_key, path, fields):
    url = f"https://api.kavenegar.com/v1/{api_key}/{path}"
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
    except urllib.error.URLError:
        logger.warning("kavenegar %s could not connect", path)
        raise SmsError("پیامک ارسال نشد. کمی بعد دوباره تلاش کن.")
    try:
        payload = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        logger.warning("kavenegar %s returned an unreadable response", path)
        raise SmsError("پیامک ارسال نشد. کلید، نام قالب و شارژ پنل کاوه‌نگار را بررسی کن.")
    status = (payload.get("return") or {}).get("status")
    if status != 200:
        logger.warning("kavenegar %s status %s", path, status)
        raise SmsError("پیامک ارسال نشد. کلید، نام قالب و شارژ پنل کاوه‌نگار را بررسی کن.")


def deliver_plain(phone, message):
    api_key, _template = credentials()
    if not api_key:
        raise SmsError("کلید یا نام قالب کاوه‌نگار در پنل ذخیره نشده.")
    _kavenegar(api_key, "sms/send.json", {"receptor": phone, "message": message})


def deliver_code(phone, code, host="85.198.54.48"):
    api_key, template = credentials()
    if not api_key:
        raise SmsError("کلید یا نام قالب کاوه‌نگار در پنل ذخیره نشده.")
    host = (host or "85.198.54.48").split(":")[0].strip() or "85.198.54.48"
    # The last line is what Chrome reads when the user taps Allow.
    message = f"کد ورود فیکسوگرام: {code}\n@{host} #{code}"
    try:
        deliver_plain(phone, message)
        return
    except SmsError:
        logger.warning("kavenegar formatted send failed; falling back to lookup")
    if not template:
        raise SmsError("کلید یا نام قالب کاوه‌نگار در پنل ذخیره نشده.")
    _kavenegar(
        api_key,
        "verify/lookup.json",
        {"receptor": phone, "token": code, "template": template},
    )


def issue_code(phone, host="85.198.54.48"):
    now = timezone.now()
    recent = (
        LoginCode.objects.filter(
            phone=phone,
            used_at__isnull=True,
            created_at__gte=now - CODE_COOLDOWN,
        )
        .order_by("-created_at")
        .first()
    )
    if recent is not None and recent.expires_at > now and recent.attempts < CODE_ATTEMPTS:
        raise TooSoon()
    LoginCode.objects.filter(phone=phone, used_at__isnull=True).update(used_at=now)
    code = f"{secrets.randbelow(9000) + 1000}"
    row = LoginCode.objects.create(
        phone=phone,
        code_hash=make_password(code),
        expires_at=now + CODE_TTL,
    )
    try:
        deliver_code(phone, code, host)
    except Exception:
        row.delete()
        raise
    return code


def verify_code(phone, code):
    row = (
        LoginCode.objects.filter(phone=phone, used_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    now = timezone.now()
    if row is None or row.expires_at <= now:
        return "expired"
    if row.attempts >= CODE_ATTEMPTS:
        return "locked"
    if not check_password(code, row.code_hash):
        row.attempts += 1
        row.save(update_fields=["attempts"])
        if row.attempts >= CODE_ATTEMPTS:
            return "locked"
        return "wrong"
    row.used_at = now
    row.save(update_fields=["used_at"])
    return "ok"
