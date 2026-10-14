from talent.seo import defaults
from talent.copy import home_lines
from talent.models import (
    IdentityDocument,
    JobPost,
    Message,
    PhoneRequest,
    Profile,
    ProfileRole,
    Ticket,
    ViolationReport,
)


def seo(request):
    return {"seo": defaults(request)}


def home_copy(request):
    return {"home_copy": home_lines()}


def _in_panel(path):
    if path.startswith("/banners/") and path.rstrip("/").endswith("/go"):
        return False
    prefixes = (
        "/desk/",
        "/moderation/",
        "/categories/",
        "/reports/",
        "/broadcast/",
        "/support/",
        "/blog/write",
        "/banners/",
    )
    return any(path.startswith(prefix) for prefix in prefixes)


def nav(request):
    from talent.access import flags
    from talent.views import welcome_for

    welcome = welcome_for(request)
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {
            "unread_count": 0,
            "pending_count": 0,
            "moderation_count": 0,
            "ticket_count": 0,
            "my_avatar": "",
            "my_initial": "",
            "welcome": welcome,
            "staff_access": {},
            "is_visitor": False,
            "online_count": "۰",
            "online_people": [],
            "show_online_bar": False,
            "push_public_key": _push_key(),
        }
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = None
    my_avatar = profile.avatar.url if profile and profile.avatar else ""
    my_initial = ((profile.display_name if profile else "") or "ت")[:1]
    unread_count = (
        Message.objects.filter(read_at__isnull=True, status="approved")
        .exclude(sender=user)
        .filter(thread__user_low=user)
        .count()
        + Message.objects.filter(read_at__isnull=True, status="approved")
        .exclude(sender=user)
        .filter(thread__user_high=user)
        .count()
    )
    pending_count = 0
    moderation_count = 0
    ticket_count = 0
    online_count = "۰"
    online_people = []
    show_online_bar = False
    if user.is_staff:
        from talent.dates import persian_digits
        from talent.models import Presence
        from talent.traffic import online_cutoff, path_label

        cutoff = online_cutoff()
        online_count = persian_digits(Presence.objects.filter(last_seen__gte=cutoff).count())
        present = list(
            Presence.objects.filter(last_seen__gte=cutoff)
            .select_related("user__profile")
            .order_by("-last_seen")[:12]
        )
        for item in present:
            name = "مهمان"
            if item.user_id:
                try:
                    seen = item.user.profile
                except Profile.DoesNotExist:
                    seen = None
                if seen is not None and seen.display_name:
                    name = seen.display_name
                else:
                    name = item.user.username
            online_people.append({"name": name, "page": path_label(item.path)})
        show_online_bar = _in_panel(request.path)
        moderation_count = (
            Profile.objects.filter(account_status="pending").count()
            + ProfileRole.objects.filter(status=ProfileRole.Status.PENDING).count()
            + Message.objects.filter(status="pending").count()
            + JobPost.objects.filter(status=JobPost.Status.PENDING).count()
            + PhoneRequest.objects.filter(status=PhoneRequest.Status.PENDING).count()
            + IdentityDocument.objects.filter(status=IdentityDocument.Status.PENDING).count()
        )
        ticket_count = (
            Ticket.objects.filter(status=Ticket.Status.OPEN).count()
            + ViolationReport.objects.filter(status=ViolationReport.Status.PENDING).count()
        )
        pending_count = moderation_count + ticket_count
    return {
        "unread_count": unread_count,
        "pending_count": pending_count,
        "moderation_count": moderation_count,
        "ticket_count": ticket_count,
        "online_count": online_count,
        "online_people": online_people,
        "show_online_bar": show_online_bar,
        "my_avatar": my_avatar,
        "my_initial": my_initial,
        "welcome": welcome,
        "staff_access": flags(user),
        "is_visitor": bool(profile and profile.is_visitor and not user.is_staff),
        "push_public_key": _push_key(),
    }


def _push_key():
    try:
        from talent.push import public_key

        return public_key()
    except Exception:
        return ""
