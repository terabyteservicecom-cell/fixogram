import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.urls import reverse
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush

from talent.models import PushSubscription

_KEYS = None


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def vapid_keys():
    global _KEYS
    if _KEYS:
        return _KEYS
    public = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    private = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if public and private:
        _KEYS = (public, private)
        return _KEYS
    path = Path(settings.BASE_DIR) / "private" / "vapid.json"
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = {}
        if saved.get("public") and saved.get("private"):
            _KEYS = (saved["public"], saved["private"])
            return _KEYS
    vapid = Vapid01()
    vapid.generate_keys()
    private = _b64url(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
    public = _b64url(
        vapid.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"public": public, "private": private}), encoding="utf-8")
    except OSError:
        pass
    _KEYS = (public, private)
    return _KEYS


def public_key():
    return vapid_keys()[0]


def notify_message(message):
    if message is None or message.status != "approved":
        return 0
    thread = message.thread
    if thread.user_low_id == message.sender_id:
        recipient_id = thread.user_high_id
    else:
        recipient_id = thread.user_low_id
    if recipient_id == message.sender_id:
        return 0
    profile = getattr(message.sender, "profile", None)
    name = profile.display_name if profile and profile.display_name else message.sender.username
    preview = " ".join((message.body or "").split())[:80]
    body = f"{name}: {preview}" if name else preview
    payload = {
        "title": "پیام تازه در فیکسوگرام",
        "body": body,
        "url": reverse("thread", args=[message.thread_id]),
        "tag": f"msg-{message.id}",
    }
    sent = 0
    for sub in PushSubscription.objects.filter(user_id=recipient_id):
        if _send(sub, payload):
            sent += 1
    return sent


def _send(sub, payload):
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid_keys()[1],
            vapid_claims={"sub": "https://www.tamirneshan.ir"},
            ttl=60 * 60 * 24,
        )
    except WebPushException as exc:
        if exc.status_code in (404, 410):
            sub.delete()
        return False
    except Exception:
        return False
    return True
