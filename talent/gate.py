from django.contrib import messages
from django.shortcuts import redirect

from talent.access import guard_for, can, summarize
from talent.pwa import INSTALL_PATHS
from talent.models import StaffLog


class VisitorGate:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or user.is_staff:
            return self.get_response(request)
        profile = getattr(user, "profile", None)
        if profile is None or not profile.is_visitor:
            return self.get_response(request)
        path = request.path
        if (
            path.startswith("/field/")
            or path.startswith("/static/")
            or path.startswith("/media/")
            or path.startswith("/logout")
            or path.startswith("/favicon")
            or path in ("/app-sw.js", "/sw.js", "/manifest.webmanifest")
        ):
            return self.get_response(request)
        return redirect("field_desk")


class SupportGate:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in INSTALL_PATHS:
            return self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_staff and not user.is_superuser:
            if request.path.startswith("/admin/"):
                messages.error(request, "ویرایش رکوردها فقط برای مدیر است.")
                return redirect("desk")
            code = guard_for(request.path)
            if code and not can(user, code):
                messages.error(request, "این بخش برای تو باز نیست.")
                return redirect("desk")
        response = self.get_response(request)
        self._log(request, response)
        return response

    def _log(self, request, response):
        user = getattr(request, "user", None)
        if request.method != "POST" or user is None or not user.is_authenticated:
            return
        if not user.is_staff or user.is_superuser or response.status_code >= 400:
            return
        if not getattr(getattr(user, "profile", None), "is_support", False):
            return
        StaffLog.objects.create(user=user, path=request.path[:200], summary=summarize(request))
