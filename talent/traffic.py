from datetime import timedelta

from django.utils import timezone

from talent.dates import persian_digits
from talent.models import PageView, Presence

ONLINE_MINUTES = 5


def path_label(path):
    if path in ("", "/"):
        return "صفحه جستجو"
    labels = (
        ("/jobs/", "استخدام و کاریابی"),
        ("/blog/", "بلاگ"),
        ("/desk/", "پنل"),
        ("/reports/visits/", "گزارش بازدید"),
        ("/reports/", "گزارشات"),
        ("/banners/report/", "گزارش کلیک بنر"),
        ("/banners/", "بنرها"),
        ("/moderation/", "صف تایید"),
        ("/categories/", "دسته‌ها"),
        ("/messages/", "پیام‌ها"),
        ("/wallet/", "کیف پول"),
        ("/me/", "صفحه من"),
        ("/login/", "ورود"),
        ("/signup/", "ثبت‌نام"),
    )
    for prefix, label in labels:
        if path.startswith(prefix):
            return label
    if path.startswith("/s/"):
        return "صفحه یک دسته"
    if path.startswith("/p/"):
        return "صفحه متخصص"
    return path


def online_cutoff():
    return timezone.now() - timedelta(minutes=ONLINE_MINUTES)


def stamp_job_views(posts, viewer):
    posts = list(posts)
    staff = bool(getattr(viewer, "is_authenticated", False) and viewer.is_staff)
    viewer_id = viewer.id if getattr(viewer, "is_authenticated", False) else None
    tracked = []
    for post in posts:
        post.show_views = staff or viewer_id == post.author_id
        post.view_line = ""
        if post.show_views:
            tracked.append(post)
    if not tracked:
        return posts
    paths = {f"/jobs/{post.pk}/": post.pk for post in tracked}
    authors = {post.pk: post.author_id for post in tracked}
    totals = {post.pk: 0 for post in tracked}
    people = {post.pk: set() for post in tracked}
    rows = PageView.objects.filter(path__in=paths).values_list(
        "path", "session_key", "user_id", "user__is_staff"
    )
    for path, session_key, user_id, is_staff in rows:
        pk = paths.get(path)
        if pk is None or user_id == authors.get(pk) or is_staff:
            continue
        totals[pk] += 1
        people[pk].add(session_key)
    for post in tracked:
        post.view_line = (
            f"بازدید {persian_digits(totals[post.pk])}"
            f" · {persian_digits(len(people[post.pk]))} نفر"
        )
    return posts


class VisitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "GET" and _trackable(request.path):
            _record(request)
        return self.get_response(request)


def _trackable(path):
    if path in ("/sw.js", "/app-sw.js", "/manifest.webmanifest") or path.startswith("/favicon"):
        return False
    if path.startswith("/static/") or path.startswith("/media/"):
        return False
    return True


def _record(request):
    if not request.session.session_key:
        request.session.save()
    key = request.session.session_key
    if not key:
        return
    path = request.path[:200]
    user = request.user if getattr(request, "user", None) is not None and request.user.is_authenticated else None
    now = timezone.now()
    PageView.objects.create(path=path, session_key=key, user=user)
    Presence.objects.update_or_create(
        session_key=key,
        defaults={"user": user, "path": path, "last_seen": now},
    )
    Presence.objects.filter(last_seen__lt=now - timedelta(days=2)).delete()
