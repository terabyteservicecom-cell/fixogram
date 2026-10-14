from django.core.exceptions import ObjectDoesNotExist


PERMISSIONS = (
    ("moderate", "صف تایید"),
    ("categories", "دسته‌ها"),
    ("banners", "بنرها"),
    ("blog", "بلاگ"),
    ("broadcast", "پیام گروهی"),
    ("tickets", "تیکت و تخلف"),
    ("reports", "گزارشات"),
)

GUARDS = (
    ("/moderation/", "moderate"),
    ("/desk/users/", "moderate"),
    ("/desk/jobs/", "moderate"),
    ("/categories/", "categories"),
    ("/banners/", "banners"),
    ("/blog/write", "blog"),
    ("/broadcast/", "broadcast"),
    ("/support/", "tickets"),
    ("/reports/", "reports"),
)


def can(user, code):
    if not getattr(user, "is_authenticated", False) or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    access = getattr(profile, "access", None) if profile is not None else None
    if access is None:
        return True
    return bool(getattr(access, code, False))


def flags(user):
    return {code: can(user, code) for code, _label in PERMISSIONS}


def guard_for(path):
    if "/banners/" in path and path.rstrip("/").endswith("/go"):
        return ""
    for prefix, code in GUARDS:
        if path.startswith(prefix):
            return code
    return ""


def summarize(request):
    kind = (request.POST.get("kind") or request.POST.get("form") or "").strip()
    action = (request.POST.get("action") or "").strip()
    names = {
        "signup": "بررسی ثبت‌نام",
        "role": "بررسی تخصص",
        "message": "بررسی پیام",
        "job": "بررسی آگهی",
        "phone": "بررسی شماره",
        "identity": "بررسی ابراز هویت",
        "create-user": "ساخت کاربر",
        "create-support": "ساخت پشتیبان",
        "edit-support": "ویرایش پشتیبان",
        "delete-support": "حذف پشتیبان",
        "access": "تغییر دسترسی پشتیبان",
        "account": "حساب",
        "phone_edit": "عوض کردن شماره",
        "seo": "سئوی کاربر",
        "category_seo": "سئوی دسته",
        "blog_category_seo": "سئوی دسته بلاگ",
        "page_seo": "سئوی صفحه ثابت",
        "home_copy": "نوشته صفحه اصلی",
        "category": "دسته",
        "category_edit": "ویرایش دسته",
        "category_delete": "حذف دسته",
        "new_category": "دسته تازه",
        "welcome": "اطلاعیه",
        "post": "نوشته بلاگ",
        "ticket": "تیکت",
    }
    label = names.get(kind) or request.path
    actions = {
        "approve": "تایید",
        "reject": "رد",
        "delete": "حذف",
        "archive": "بایگانی",
        "restore": "بازگشت",
        "deactivate": "غیرفعال",
        "activate": "فعال",
        "close": "بستن",
        "reply": "پاسخ",
        "review": "رسیدگی",
        "dismiss": "رد",
        "grant": "دادن",
        "revoke": "برداشتن",
    }
    if action:
        label = f"{label} — {actions.get(action, action)}"
    return label[:200]


def rows_for(profile):
    try:
        access = profile.access
    except ObjectDoesNotExist:
        access = None
    return [
        {
            "code": code,
            "label": label,
            "on": True if access is None else bool(getattr(access, code)),
        }
        for code, label in PERMISSIONS
    ]
