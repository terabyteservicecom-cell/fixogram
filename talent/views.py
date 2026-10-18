import csv
import json
import mimetypes
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse, reverse_lazy
from django.core.exceptions import ValidationError
from django.forms import ValidationError as FormError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Exists, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import TruncDate
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from talent.copy import home_fields, job_warning_text, save_home_lines, save_job_warning
from talent.cities import CITY_OF, city_choices
from talent.access import PERMISSIONS, can, rows_for
from talent.billing import approve_charge, buy_year, public_profiles, toman, viewer_can_open, wallet_for, year_price
from talent.seo import (
    attach_audit,
    blog_index,
    blog_post,
    clean_seo_pair,
    home_page,
    jobs_page,
    page_seo_rows,
    profile_audit,
    profile_page,
    robots_txt as robots_body,
    section_page,
    sitemap_xml as sitemap_body,
    terms_page,
)
from talent.dates import jalali_datetime, jalali_label, parse_day, persian_digits
from talent.push import notify_message
from talent.traffic import ONLINE_MINUTES, online_cutoff, path_label, stamp_job_views
from talent.forms import (
    BannerForm,
    BlogCategoryForm,
    ChargeForm,
    GroupMessageForm,
    JobForm,
    ForgotUsernameForm,
    LoginForm,
    MessageForm,
    CodeForm,
    SimplePasswordChangeForm,
    SmsSettingForm,
    PhotoForm,
    accounts_for_phone,
    phone_taken,
    validate_phone,
    validate_contact_phone,
    PostCommentForm,
    PostForm,
    ProfileForm,
    StaffUserForm,
    SupportAccountForm,
    VisitorAccountForm,
    VisitorRecruitForm,
    store_visit_file,
    IdentityForm,
    RatingForm,
    ResumeForm,
    SignupForm,
    NewCategoryForm,
    TicketForm,
    TicketReplyForm,
    ViolationForm,
    SubcategoryForm,
    WelcomeForm,
)
from talent.geo import haversine_km
from talent.sms import SmsError, TooSoon, deliver_plain, issue_code, verify_code
from talent.cities import CITIES
from talent.provinces import PROVINCES, province_choices
from talent.models import (
    Banner,
    Bookmark,
    VisitorSettlement,
    BannerClick,
    BlogCategory,
    Category,
    ChargeRequest,
    Wallet,
    WalletEntry,
    GroupMessage,
    IdentityDocument,
    JobPost,
    Message,
    PageSeo,
    PageView,
    PhoneRequest,
    Photo,
    PushSubscription,
    Presence,
    Post,
    PostComment,
    Profile,
    ProfileRole,
    SmsSetting,
    StaffLog,
    SupportAccess,
    Rating,
    Ticket,
    ViolationReport,
    ResumeItem,
    Role,
    Thread,
    WelcomeMessage,
)


class PersianPasswordChange(PasswordChangeView):
    template_name = "talent/password.html"
    form_class = SimplePasswordChangeForm
    success_url = reverse_lazy("dashboard")

    def form_valid(self, form):
        messages.success(self.request, "رمز عوض شد.")
        return super().form_valid(form)


def profile_for(user):
    profile, _ = Profile.objects.get_or_create(
        user=user,
        defaults={"display_name": user.username},
    )
    return profile


def ready_welcome():
    note = WelcomeMessage.objects.order_by("pk").first()
    if note is None or not note.is_ready():
        return None
    return note


def pending_welcome(profile):
    note = ready_welcome()
    if note is None:
        return None
    if profile.welcome_seen_at and profile.welcome_seen_at >= note.updated_at:
        return None
    return note


def welcome_for(request):
    note = ready_welcome()
    if note is None:
        return None
    stamp = note.updated_at.isoformat()
    if (request.COOKIES.get("welcome_off") or "") >= stamp:
        return None
    if request.user.is_authenticated:
        return pending_welcome(profile_for(request.user))
    hidden = request.session.get("welcome_hidden_at")
    if hidden and hidden >= stamp:
        return None
    return note


def save_welcome(form):
    note = WelcomeMessage.objects.order_by("pk").first() or WelcomeMessage()
    note.body = form.cleaned_data["body"]
    if form.cleaned_data.get("clear_audio") and note.audio:
        note.audio.delete(save=False)
    if form.cleaned_data["audio"]:
        if note.audio:
            note.audio.delete(save=False)
        note.audio = form.cleaned_data["audio"]
    if form.cleaned_data.get("clear_video") and note.video:
        note.video.delete(save=False)
    if form.cleaned_data["video"]:
        if note.video:
            note.video.delete(save=False)
        note.video = form.cleaned_data["video"]
    note.is_active = bool(form.cleaned_data.get("is_active"))
    note.save()
    return note


def visible_username(user, phone):
    if user.username and user.username != phone:
        return user.username
    return ""


def username_recovery_message(user, phone):
    name = visible_username(user, phone)
    if name:
        return f"نام کاربری فیکسوگرام: {name}\nورود با شماره موبایل و کد پیامکی است."
    return "ورود فیکسوگرام با همین شماره موبایل است. نام کاربری جدا تنظیم نکرده‌ای."


def can_see_phone(user, profile):
    if not profile.contact_phone or not user.is_authenticated:
        return False
    if user.id == profile.user_id or user.is_staff:
        return True
    return PhoneRequest.objects.filter(
        requester=user,
        profile=profile,
        status=PhoneRequest.Status.APPROVED,
    ).exists()


def parse_coordinate(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def nearby_profiles(profiles, lat, lng, radius_km):
    ranked = []
    for profile in profiles:
        if profile.latitude is None or profile.longitude is None:
            continue
        distance = haversine_km(lat, lng, profile.latitude, profile.longitude)
        if distance <= radius_km:
            profile.distance_km = round(distance, 1)
            ranked.append(profile)
    ranked.sort(key=lambda item: (item.distance_km, -(item.score_avg or 0)))
    return ranked


def bookmark_ids(user, kind):
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(Bookmark.objects.filter(user=user, kind=kind).values_list("object_id", flat=True))


def bookmark_saved(user, kind, object_id):
    return object_id in bookmark_ids(user, kind)


def bookmark_allowed(request, kind, object_id):
    if kind == Bookmark.Kind.SECTION:
        return Category.objects.filter(pk=object_id).exists()
    if kind == Bookmark.Kind.PROFILE:
        profile = Profile.objects.select_related("user").filter(pk=object_id).first()
        return profile is not None and viewer_can_open(request.user, profile)
    if kind == Bookmark.Kind.JOB:
        post = JobPost.objects.filter(pk=object_id).first()
        if post is None:
            return False
        visible = (
            post.status == JobPost.Status.APPROVED
            and post.expires_at is not None
            and post.expires_at > timezone.now()
        )
        owner = request.user.is_authenticated and request.user.id == post.author_id
        staff = request.user.is_authenticated and request.user.is_staff
        return visible or owner or staff
    if kind == Bookmark.Kind.POST:
        post = Post.objects.filter(pk=object_id).first()
        if post is None:
            return False
        return post.is_published or (request.user.is_authenticated and request.user.is_staff)
    return False


def safe_bookmark_next(request):
    target = (request.POST.get("next") or "").strip()
    if not target.startswith("/") or target.startswith("//"):
        return reverse("bookmarks")
    return target


def bookmark_rows(user):
    marks = list(Bookmark.objects.filter(user=user))
    grouped = {kind: [] for kind, _label in Bookmark.Kind.choices}
    for mark in marks:
        grouped.setdefault(mark.kind, []).append(mark.object_id)
    sections = {row.pk: row for row in Category.objects.filter(pk__in=grouped[Bookmark.Kind.SECTION])}
    profiles = {
        row.pk: row
        for row in Profile.objects.select_related("user").filter(pk__in=grouped[Bookmark.Kind.PROFILE])
    }
    jobs = {row.pk: row for row in JobPost.objects.filter(pk__in=grouped[Bookmark.Kind.JOB])}
    posts = {row.pk: row for row in Post.objects.filter(pk__in=grouped[Bookmark.Kind.POST])}
    rows = []
    for mark in marks:
        title = "این مورد حذف شده"
        url = ""
        note = ""
        if mark.kind == Bookmark.Kind.SECTION and mark.object_id in sections:
            item = sections[mark.object_id]
            title = item.name
            url = reverse("section", args=[item.slug])
        elif mark.kind == Bookmark.Kind.PROFILE and mark.object_id in profiles:
            item = profiles[mark.object_id]
            title = item.display_name or "بدون نام"
            if viewer_can_open(user, item):
                url = reverse("profile", args=[item.pk])
            else:
                note = "الان دیده نمی‌شود"
        elif mark.kind == Bookmark.Kind.JOB and mark.object_id in jobs:
            item = jobs[mark.object_id]
            title = item.title
            visible = (
                item.status == JobPost.Status.APPROVED
                and item.expires_at is not None
                and item.expires_at > timezone.now()
            )
            if visible or item.author_id == user.id or user.is_staff:
                url = reverse("job_detail", args=[item.pk])
            else:
                note = "این آگهی دیگر نمایش داده نمی‌شود"
        elif mark.kind == Bookmark.Kind.POST and mark.object_id in posts:
            item = posts[mark.object_id]
            title = item.title
            if item.is_published or user.is_staff:
                url = reverse("blog_detail", args=[item.pk])
            else:
                note = "این نوشته منتشر نیست"
        rows.append({
            "kind": mark.kind,
            "kind_label": mark.get_kind_display(),
            "object_id": mark.object_id,
            "title": title,
            "url": url,
            "note": note,
        })
    return rows


@login_required
def bookmarks(request):
    return render(request, "talent/bookmarks.html", {"rows": bookmark_rows(request.user)})


@login_required
@require_POST
def toggle_bookmark(request):
    kind = (request.POST.get("kind") or "").strip()
    raw_id = (request.POST.get("id") or "").strip()
    if kind not in Bookmark.Kind.values or not raw_id.isdigit():
        raise Http404("این ذخیره پیدا نشد.")
    object_id = int(raw_id)
    existing = Bookmark.objects.filter(user=request.user, kind=kind, object_id=object_id)
    if existing.exists():
        existing.delete()
        messages.success(request, "از ذخیره‌ها برداشته شد.")
        return redirect(safe_bookmark_next(request))
    if not bookmark_allowed(request, kind, object_id):
        raise Http404("این مورد الان ذخیره نمی‌شود.")
    else:
        try:
            Bookmark.objects.create(user=request.user, kind=kind, object_id=object_id)
        except IntegrityError:
            pass
        messages.success(request, "ذخیره شد.")
    return redirect(safe_bookmark_next(request))


def specialist_listing(request, locked_category=None):
    profiles = public_profiles().select_related("user").annotate(
        score_avg=Avg("ratings__score"),
        score_count=Count("ratings", distinct=True),
    )
    q = request.GET.get("q", "").strip()
    province = request.GET.get("city", "").strip()
    town = request.GET.get("town", "").strip()
    role_id = request.GET.get("role", "").strip()
    category_id = request.GET.get("category", "").strip()
    if locked_category is not None:
        category_id = str(locked_category.pk)
    verified = request.GET.get("verified") == "1"
    lat = parse_coordinate(request.GET.get("lat"))
    lng = parse_coordinate(request.GET.get("lng"))
    radius = parse_coordinate(request.GET.get("radius")) or 20

    if q:
        profiles = profiles.filter(
            Q(display_name__icontains=q)
            | Q(business_name__icontains=q)
            | Q(headline__icontains=q)
            | Q(bio__icontains=q)
            | Q(about_business__icontains=q)
            | Q(city__icontains=q)
            | Q(province__icontains=q)
            | Q(address__icontains=q)
            | Q(
                role_links__role__name__icontains=q,
                role_links__status=ProfileRole.Status.APPROVED,
            )
            | Q(
                role_links__role__category__name__icontains=q,
                role_links__status=ProfileRole.Status.APPROVED,
            )
            | Q(
                role_links__role__category__parent__name__icontains=q,
                role_links__status=ProfileRole.Status.APPROVED,
            )
        )
    if province in PROVINCES:
        profiles = profiles.filter(Q(province=province) | Q(city=province))
    if town:
        profiles = profiles.filter(city__icontains=town)
    if role_id.isdigit():
        profiles = profiles.filter(
            role_links__role_id=int(role_id),
            role_links__status=ProfileRole.Status.APPROVED,
        )
    if category_id.isdigit():
        chosen = Category.objects.filter(pk=int(category_id)).first()
        if chosen is not None:
            profiles = profiles.filter(
                role_links__role__category_id__in=chosen.descendant_ids(),
                role_links__status=ProfileRole.Status.APPROVED,
            )
    if verified:
        profiles = profiles.filter(role_links__status=ProfileRole.Status.APPROVED)

    profiles = profiles.distinct()
    if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
        profiles = nearby_profiles(profiles, lat, lng, radius)
        result_count = len(profiles)
    else:
        profiles = profiles.order_by("-score_avg", "-created_at")
        result_count = profiles.count()
    page = Paginator(profiles, 12).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    roots = list(
        Category.objects.filter(parent__isnull=True).prefetch_related("children__children", "children__children__children")
    )
    categories = []

    def collect(category):
        categories.append(category)
        for child in category.children.all():
            collect(child)

    for root in roots:
        collect(root)
    section_banners = {
        banner.category_id: banner
        for banner in Banner.objects.filter(is_active=True, place=Banner.Place.SECTION, category__isnull=False)
    }
    saved_sections = bookmark_ids(request.user, Bookmark.Kind.SECTION)
    section_cards = [
        {
            "category": category,
            "banner": section_banners.get(category.pk),
            "saved": category.pk in saved_sections,
        }
        for category in roots
    ]
    topic_hits = []
    if q:
        topic_hits.extend(
            {"kind": "دسته", "label": category.name, "url": f"/s/{category.slug}/"}
            for category in Category.objects.filter(name__icontains=q).select_related("parent")[:8]
        )
        topic_hits.extend(
            {
                "kind": "تخصص",
                "label": f"{role.category.name} — {role.name}",
                "url": f"/?role={role.pk}",
            }
            for role in Role.objects.filter(name__icontains=q).select_related("category")[:8]
        )
        topic_hits.extend(
            {
                "kind": post.get_kind_display(),
                "label": post.title,
                "url": f"/jobs/?q={q}",
            }
            for post in JobPost.visible()
            .filter(Q(title__icontains=q) | Q(body__icontains=q) | Q(city__icontains=q))[:6]
        )
    return {
        "page": page,
        "querystring": params.urlencode(),
        "categories": categories,
        "section_cards": section_cards,
        "topic_hits": topic_hits,
        "roles": Role.objects.select_related("category"),
        "provinces": PROVINCES,
        "cities": CITIES,
        "result_count": result_count,
        "banners": Banner.objects.filter(is_active=True, place=Banner.Place.HOME)[:3],
        "locked_category": locked_category,
        "recent_jobs": JobPost.visible().select_related(
            "author__profile", "category"
        )[:4],
    }


def home(request):
    context = specialist_listing(request)
    context["welcome"] = welcome_for(request)
    context["seo"] = home_page(request)
    return render(request, "talent/home.html", context)


def section(request, slug):
    category = get_object_or_404(Category.objects.select_related("parent"), slug=slug)
    context = specialist_listing(request, locked_category=category)
    context["banners"] = Banner.objects.filter(
        is_active=True,
        place=Banner.Place.SECTION,
        category=category,
    ).order_by("order", "id")[:2]
    context["section"] = category
    context["item_saved"] = bookmark_saved(request.user, Bookmark.Kind.SECTION, category.pk)
    context["welcome"] = welcome_for(request)
    context["seo"] = section_page(request, category)
    return render(request, "talent/section.html", context)


def robots_txt(request):
    return robots_body(request)


def sitemap_xml(request):
    return sitemap_body(request)


def opened_profile(request, pk):
    profile = get_object_or_404(Profile, pk=pk)
    if not viewer_can_open(request.user, profile):
        raise Http404("این صفحه الان برای دیگران باز نیست.")
    return profile


def profile_detail(request, pk):
    profile = get_object_or_404(
        Profile.objects.select_related("user").prefetch_related(
            "photos",
            "resume_items",
            "role_links__role__category",
            "ratings__rater__profile",
        ),
        pk=pk,
    )
    if not viewer_can_open(request.user, profile):
        raise Http404("این صفحه الان برای دیگران باز نیست.")
    phone_request = None
    if request.user.is_authenticated and request.user.id != profile.user_id:
        phone_request = PhoneRequest.objects.filter(
            requester=request.user,
            profile=profile,
        ).first()
    my_rating = None
    if request.user.is_authenticated:
        my_rating = Rating.objects.filter(rater=request.user, profile=profile).first()
    average, count = profile.score_summary()
    return render(
        request,
        "talent/profile.html",
        {
            "profile": profile,
            "approved_roles": profile.role_links.filter(status=ProfileRole.Status.APPROVED),
            "can_see_phone": can_see_phone(request.user, profile),
            "phone_request": phone_request,
            "rating_form": RatingForm(instance=my_rating),
            "my_rating": my_rating,
            "average": average,
            "rating_count": count,
            "public_username": visible_username(profile.user, profile.phone),
            "welcome": welcome_for(request),
            "seo": profile_page(request, profile),
            "item_saved": bookmark_saved(request.user, Bookmark.Kind.PROFILE, profile.pk),
        },
    )


def account_for_phone(phone):
    accounts = accounts_for_phone(phone)
    if accounts:
        staff = [account for account in accounts if account.is_staff]
        return (staff or accounts)[0], False
    try:
        with transaction.atomic():
            user = User(username=phone)
            user.set_unusable_password()
            user.save()
            profile = profile_for(user)
            profile.phone = phone
            profile.display_name = ""
            profile.save()
    except IntegrityError:
        accounts = accounts_for_phone(phone)
        if accounts:
            return accounts[0], False
        raise
    return user, True


def open_account(request, user):
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, "وارد شدی.")
    if profile_for(user).is_visitor:
        return redirect("field_desk")
    return redirect("dashboard")


def login_block_reason(user):
    if user is None:
        return "این شماره ثبت نشده. اول ثبت‌نام کن."
    if not user.is_active:
        return "این حساب غیرفعال شده است."
    return ""


def terms(request):
    return render(request, "talent/terms.html", {"seo": terms_page(request)})


def enter(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    signing_up = request.resolver_match.url_name == "signup"
    form_class = SignupForm if signing_up else LoginForm
    form = form_class(request.POST or None)
    if not signing_up and request.method == "GET":
        request.session.pop("login_phone", None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        if signing_up:
            if phone_taken(phone):
                messages.error(request, "این شماره قبلاً ثبت شده. از صفحه ورود استفاده کن.")
                return redirect("login")
            try:
                with transaction.atomic():
                    if phone_taken(phone):
                        raise IntegrityError("phone taken")
                    user = User(username=phone)
                    user.set_unusable_password()
                    user.save()
                    profile = profile_for(user)
                    profile.phone = phone
                    profile.display_name = form.cleaned_data["display_name"]
                    profile.account_status = "pending"
                    profile.accepted_terms_at = timezone.now()
                    profile.save()
            except IntegrityError:
                messages.error(request, "این شماره قبلاً ثبت شده. از صفحه ورود استفاده کن.")
                return redirect("login")
            try:
                issue_code(phone, request.get_host())
            except TooSoon:
                request.session["login_phone"] = phone
                messages.info(request, "کد قبلی هنوز معتبر است. همان را وارد کن.")
                return redirect("login_code")
            except SmsError as exc:
                messages.error(request, f"ثبت‌نام شد، ولی پیامک نرفت. از صفحه ورود دوباره کد بگیر. {exc}")
                return redirect("login")
            request.session["login_phone"] = phone
            messages.success(request, "ثبت‌نام شد. کد ورود پیامک شد. بعد از ورود اطلاعات را کامل کن؛ تا تایید مدیر یا پشتیبان در جستجو دیده نمی‌شوی.")
            return redirect("login_code")
        reason = login_block_reason((accounts_for_phone(phone) or [None])[0])
        if reason:
            form.add_error(None, reason)
        else:
            try:
                issue_code(phone, request.get_host())
            except TooSoon:
                request.session["login_phone"] = phone
                messages.info(request, "کد قبلی هنوز معتبر است. همان را وارد کن یا یک دقیقه بعد کد تازه بگیر.")
                return redirect("login_code")
            except SmsError as exc:
                form.add_error(None, str(exc))
            else:
                request.session["login_phone"] = phone
                return redirect("login_code")
    return render(
        request,
        "talent/enter.html",
        {"form": form, "signing_up": signing_up},
    )


@staff_member_required(login_url="login")
def sms_settings(request):
    if not request.user.is_superuser:
        raise Http404
    row = SmsSetting.current()
    form = SmsSettingForm(request.POST or None, initial={"template": row.template})
    if request.method == "POST" and form.is_valid():
        key = form.cleaned_data["api_key"].strip()
        if key:
            row.api_key = key
        elif not row.api_key:
            form.add_error("api_key", "کلید API را از پنل کاوه‌نگار اینجا بگذار.")
        if not form.errors:
            row.template = form.cleaned_data["template"]
            row.save()
            messages.success(request, "تنظیم پیامک ذخیره شد.")
            return redirect("sms_settings")
    masked = ""
    if row.api_key:
        masked = "••••" + row.api_key[-4:]
    return render(
        request,
        "talent/sms.html",
        {"form": form, "masked_key": masked, "template_name": row.template},
    )


def login_code(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    phone = request.session.get("login_phone")
    if not phone:
        return redirect("login")
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        result = verify_code(phone, form.cleaned_data["code"])
        if result == "ok":
            user = (accounts_for_phone(phone) or [None])[0]
            reason = login_block_reason(user)
            if reason or user is None:
                form.add_error(None, reason or "این شماره ثبت نشده. اول ثبت‌نام کن.")
            else:
                request.session.pop("login_phone", None)
                return open_account(request, user)
        elif result == "expired":
            form.add_error("code", "این کد منقضی شده. دوباره کد بگیر.")
        elif result == "locked":
            form.add_error("code", "تلاش‌ها تمام شد. یک کد تازه بگیر.")
        else:
            form.add_error("code", "کد اشتباه است.")
    return render(request, "talent/login_code.html", {"form": form, "phone": phone})


def forgot_username(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = ForgotUsernameForm(request.POST or None)
    if request.method == "GET":
        request.session.pop("recover_phone", None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        reason = login_block_reason((accounts_for_phone(phone) or [None])[0])
        if reason:
            form.add_error(None, reason)
        else:
            try:
                issue_code(phone, request.get_host())
            except TooSoon:
                request.session["recover_phone"] = phone
                messages.info(request, "کد قبلی هنوز معتبر است. همان را وارد کن.")
                return redirect("forgot_username_code")
            except SmsError as exc:
                form.add_error(None, str(exc))
            else:
                request.session["recover_phone"] = phone
                return redirect("forgot_username_code")
    return render(request, "talent/forgot_username.html", {"form": form})


def forgot_username_code(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    phone = request.session.get("recover_phone")
    if not phone:
        return redirect("forgot_username")
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        result = verify_code(phone, form.cleaned_data["code"])
        if result == "ok":
            user = (accounts_for_phone(phone) or [None])[0]
            reason = login_block_reason(user)
            if reason or user is None:
                form.add_error(None, reason or "این شماره ثبت نشده. اول ثبت‌نام کن.")
            else:
                profile = profile_for(user)
                text = username_recovery_message(user, profile.phone)
                try:
                    deliver_plain(phone, text)
                except SmsError as exc:
                    form.add_error(None, str(exc))
                else:
                    request.session.pop("recover_phone", None)
                    return render(
                        request,
                        "talent/forgot_username_done.html",
                        {
                            "phone": phone,
                            "username": visible_username(user, profile.phone),
                        },
                    )
        elif result == "expired":
            form.add_error("code", "این کد منقضی شده. دوباره کد بگیر.")
        elif result == "locked":
            form.add_error("code", "تلاش‌ها تمام شد. یک کد تازه بگیر.")
        else:
            form.add_error("code", "کد اشتباه است.")
    return render(request, "talent/forgot_username_code.html", {"form": form, "phone": phone})


@login_required
def dashboard(request):
    profile = profile_for(request.user)
    photo_form = PhotoForm()
    resume_form = ResumeForm()
    identity_form = IdentityForm()
    welcome_note = WelcomeMessage.objects.order_by("pk").first()
    welcome_form = WelcomeForm(note=welcome_note)
    profile_form = ProfileForm(
        initial={
            "display_name": profile.display_name,
            "business_name": profile.business_name,
            "province": profile.province,
            "city": profile.city,
            "address": profile.address,
            "headline": profile.headline,
            "bio": profile.bio,
            "about_business": profile.about_business,
            "phone": profile.phone,
            "contact_phone": profile.contact_phone,
            "instagram": profile.instagram,
            "telegram": profile.telegram,
            "whatsapp": profile.whatsapp,
            "website": profile.website,
            "latitude": profile.latitude,
            "longitude": profile.longitude,
            "username": visible_username(request.user, profile.phone),
        },
        user=request.user,
    )

    if request.method == "POST":
        kind = request.POST.get("form")
        if kind == "profile":
            profile_form = ProfileForm(
                request.POST,
                request.FILES,
                user=request.user,
                initial={"phone": profile.phone},
            )
            if profile_form.is_valid():
                profile.display_name = profile_form.cleaned_data["display_name"]
                profile.business_name = profile_form.cleaned_data["business_name"]
                profile.province = profile_form.cleaned_data["province"]
                profile.city = profile_form.cleaned_data["city"]
                profile.address = profile_form.cleaned_data["address"]
                profile.headline = profile_form.cleaned_data["headline"]
                profile.bio = profile_form.cleaned_data["bio"]
                profile.about_business = profile_form.cleaned_data["about_business"]
                profile.phone = profile_form.cleaned_data["phone"]
                profile.contact_phone = profile_form.cleaned_data["contact_phone"]
                profile.instagram = profile_form.cleaned_data["instagram"]
                profile.telegram = profile_form.cleaned_data["telegram"]
                profile.whatsapp = profile_form.cleaned_data["whatsapp"]
                profile.website = profile_form.cleaned_data["website"]
                profile.latitude = profile_form.cleaned_data["latitude"]
                profile.longitude = profile_form.cleaned_data["longitude"]
                request.user.username = profile_form.cleaned_data["username"] or profile.phone
                request.user.save(update_fields=["username"])
                if profile_form.cleaned_data["avatar"]:
                    profile.avatar = profile_form.cleaned_data["avatar"]
                profile.save()
                messages.success(request, "مشخصات ذخیره شد.")
                return redirect("dashboard")
        elif kind == "location":
            lat = parse_coordinate(request.POST.get("latitude"))
            lng = parse_coordinate(request.POST.get("longitude"))
            if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
                return JsonResponse({"ok": False}, status=400)
            profile.latitude = lat
            profile.longitude = lng
            profile.save(update_fields=["latitude", "longitude"])
            return JsonResponse({"ok": True})
        elif kind == "photo":
            photo_form = PhotoForm(request.POST, request.FILES)
            if profile.photos.count() >= 2:
                messages.error(request, "فقط دو عکس دیگر می‌شود گذاشت. برای عکس تازه، یکی را حذف کن.")
            elif photo_form.is_valid():
                photo = photo_form.save(commit=False)
                photo.profile = profile
                photo.save()
                messages.success(request, "عکس اضافه شد.")
                return redirect("dashboard")
        elif kind == "resume":
            resume_form = ResumeForm(request.POST)
            if profile.resume_items.count() >= 30:
                messages.error(request, "بیشتر از ۳۰ سابقه نمی‌شود گذاشت.")
            elif resume_form.is_valid():
                item = resume_form.save(commit=False)
                item.profile = profile
                item.save()
                messages.success(request, "سابقه به رزومه اضافه شد.")
                return redirect("dashboard")
        elif kind == "identity":
            identity_form = IdentityForm(request.POST, request.FILES)
            if profile.identity_documents.count() >= 12:
                messages.error(request, "بیشتر از ۱۲ مدرک نمی‌شود فرستاد.")
            elif identity_form.is_valid():
                IdentityDocument.objects.create(
                    profile=profile,
                    kind=identity_form.cleaned_data["kind"],
                    title=identity_form.cleaned_data["title"],
                    file=identity_form.cleaned_data["file"],
                )
                messages.success(request, "مدرک فرستاده شد. تا مدیر تایید نکند، VIP نمی‌شود و فایل برای دیگران باز نیست.")
                return redirect("dashboard")
        elif kind == "welcome-seen":
            profile.welcome_seen_at = timezone.now()
            profile.save(update_fields=["welcome_seen_at"])
            if request.POST.get("back") == "profile":
                return redirect("profile", pk=profile.pk)
            return redirect("dashboard")
        elif kind == "welcome" and request.user.is_staff:
            welcome_form = WelcomeForm(request.POST, request.FILES, note=welcome_note)
            if welcome_form.is_valid():
                save_welcome(welcome_form)
                messages.success(request, "پیام مدیر ذخیره شد. تازه‌واردها اولین بار آن را می‌بینند.")
                return redirect("dashboard")
        elif kind == "reapply" and profile.account_status == "rejected":
            profile.account_status = "pending"
            profile.rejection_note = ""
            profile.save(update_fields=["account_status", "rejection_note"])
            messages.success(request, "درخواست دوباره ثبت شد. تا تایید مدیر یا پشتیبان در جستجو دیده نمی‌شوی.")
            return redirect("dashboard")
        elif kind == "roles":
            selected = {int(item) for item in request.POST.getlist("categories") if item.isdigit()}
            _save_profile_specialties(profile, selected)
            messages.success(request, "تخصص‌ها ذخیره شد. موارد تازه بعد از تایید مدیر یا پشتیبان نشان تایید می‌گیرند.")
            return redirect("dashboard")

    specialty_status = _specialty_status(profile)
    return render(
        request,
        "talent/dashboard.html",
        {
            "profile": profile,
            "profile_form": profile_form,
            "photo_form": photo_form,
            "resume_form": resume_form,
            "identity_form": identity_form,
            "identity_documents": profile.identity_documents.all(),
            "specialty_tree": _specialty_tree(specialty_status, specialty_status),
            "welcome": pending_welcome(profile),
            "welcome_form": welcome_form,
            "welcome_note": welcome_note,
        },
    )


@login_required
@require_POST
def delete_photo(request, pk):
    Photo.objects.filter(pk=pk, profile__user=request.user).delete()
    messages.success(request, "عکس حذف شد.")
    return redirect("dashboard")


@login_required
@require_POST
def delete_resume(request, pk):
    ResumeItem.objects.filter(pk=pk, profile__user=request.user).delete()
    messages.success(request, "سابقه حذف شد.")
    return redirect("dashboard")


@login_required
@require_POST
def request_phone(request, pk):
    profile = opened_profile(request, pk)
    if profile.user_id == request.user.id:
        messages.error(request, "شماره خودتان همین حالا در صفحه شما هست.")
        return redirect("profile", pk)
    if not profile.contact_phone:
        messages.error(request, "این شخص هنوز شماره تماسی برای نمایش نگذاشته است.")
        return redirect("profile", pk)
    phone_request, created = PhoneRequest.objects.get_or_create(
        requester=request.user,
        profile=profile,
    )
    if phone_request.status == PhoneRequest.Status.APPROVED:
        messages.info(request, "شماره قبلاً برای شما باز شده است.")
    elif phone_request.status == PhoneRequest.Status.PENDING and not created:
        messages.info(request, "درخواست شما هنوز دست مدیر است.")
    else:
        phone_request.status = PhoneRequest.Status.PENDING
        phone_request.reviewed_at = None
        phone_request.save(update_fields=["status", "reviewed_at"])
        messages.success(request, "درخواست ثبت شد. بعد از تایید مدیر، شماره را همین‌جا می‌بینید.")
    return redirect("profile", pk)


@login_required
@require_POST
def rate(request, pk):
    profile = opened_profile(request, pk)
    if profile.user_id == request.user.id:
        messages.error(request, "به خودتان امتیاز نمی‌دهید.")
        return redirect("profile", pk)
    form = RatingForm(request.POST)
    if form.is_valid():
        Rating.objects.update_or_create(
            rater=request.user,
            profile=profile,
            defaults={
                "score": form.cleaned_data["score"],
                "comment": form.cleaned_data["comment"],
            },
        )
        messages.success(request, "امتیاز شما ثبت شد.")
    else:
        messages.error(request, "امتیاز را از ۱ تا ۵ انتخاب کنید.")
    return redirect("profile", pk)


@login_required
def account_can_message(request):
    profile = profile_for(request.user)
    if request.user.is_staff or profile.account_status == "approved":
        return True
    messages.error(request, "تا تایید ثبت‌نام، ارسال پیام باز نیست.")
    return False


def visible_messages(thread, user):
    return thread.messages.filter(Q(status="approved") | Q(sender=user)).select_related("sender__profile")


def start_thread(request, pk):
    profile = opened_profile(request, pk)
    if profile.user_id == request.user.id:
        messages.error(request, "به خودتان پیام نمی‌دهید.")
        return redirect("profile", pk)
    if not account_can_message(request):
        return redirect("profile", pk)
    thread = Thread.between(request.user, profile.user)
    return redirect("thread", thread.pk)


@require_POST
def dismiss_welcome(request):
    note = WelcomeMessage.objects.order_by("pk").first()
    if request.user.is_authenticated:
        profile = profile_for(request.user)
        profile.welcome_seen_at = timezone.now()
        profile.save(update_fields=["welcome_seen_at"])
    elif note is not None:
        request.session["welcome_hidden_at"] = note.updated_at.isoformat()
    next_url = request.POST.get("next") or ""
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        response = redirect(next_url)
    elif request.user.is_authenticated and request.POST.get("back") == "profile":
        response = redirect("profile", pk=request.user.profile.pk)
    else:
        response = redirect("home")
    if note is not None:
        response.set_cookie(
            "welcome_off",
            note.updated_at.isoformat(),
            max_age=60 * 60 * 24 * 365,
            samesite="Lax",
        )
    return response


def category_recipients(category, sender):
    return (
        Profile.objects.filter(
            role_links__status=ProfileRole.Status.APPROVED,
            role_links__role__category_id__in=category.descendant_ids(),
            account_status="approved",
            archived_at__isnull=True,
            user__is_active=True,
        )
        .exclude(user_id=sender.id)
        .distinct()
    )


def category_choices_for_broadcast(sender):
    choices = []

    def add(category, depth):
        count = category_recipients(category, sender).count()
        prefix = "— " * depth
        choices.append((str(category.pk), f"{prefix}{category.name} — {count} نفر"))
        for child in category.children.all():
            add(child, depth + 1)

    for root in Category.objects.filter(parent__isnull=True).prefetch_related("children"):
        add(root, 0)
    return choices


@staff_member_required(login_url="login")
def broadcast(request):
    form = GroupMessageForm(category_choices=category_choices_for_broadcast(request.user))
    if request.method == "POST":
        form = GroupMessageForm(request.POST, category_choices=category_choices_for_broadcast(request.user))
        if form.is_valid():
            category = get_object_or_404(Category, pk=form.cleaned_data["category"])
            recipients = list(category_recipients(category, request.user).select_related("user"))
            if not recipients:
                messages.error(request, "در این دسته متخصص تاییدشده‌ای برای دریافت پیام نیست.")
            else:
                text = f"پیام مدیر برای دسته {category.name}:\n{form.cleaned_data['body']}"
                for profile in recipients:
                    thread = Thread.between(request.user, profile.user)
                    message = Message.objects.create(
                        thread=thread,
                        sender=request.user,
                        body=text,
                        status="approved",
                        reviewed_at=timezone.now(),
                    )
                    notify_message(message)
                GroupMessage.objects.create(
                    author=request.user,
                    category=category,
                    body=form.cleaned_data["body"],
                    recipient_count=len(recipients),
                )
                messages.success(
                    request,
                    f"پیام برای {len(recipients)} نفر در «{category.name}» فرستاده شد و در پیام‌هایشان دیده می‌شود.",
                )
                return redirect("broadcast")
    return render(
        request,
        "talent/broadcast.html",
        {
            "form": form,
            "sent": GroupMessage.objects.select_related("category", "author__profile")[:12],
        },
    )


@login_required
def tickets(request):
    form = TicketForm()
    if request.method == "POST":
        form = TicketForm(request.POST)
        if form.is_valid():
            Ticket.objects.create(
                author=request.user,
                subject=form.cleaned_data["subject"],
                body=form.cleaned_data["body"],
            )
            messages.success(request, "تیکت ثبت شد. پاسخ مدیر یا پشتیبان همین‌جا دیده می‌شود.")
            return redirect("tickets")
    return render(
        request,
        "talent/tickets.html",
        {
            "form": form,
            "tickets": Ticket.objects.filter(author=request.user),
        },
    )


@login_required
def report_profile(request, pk):
    profile = opened_profile(request, pk)
    if profile.user_id == request.user.id:
        messages.error(request, "گزارش تخلف برای حساب خودت ثبت نمی‌شود.")
        return redirect("profile", pk)
    existing = ViolationReport.objects.filter(
        reporter=request.user,
        profile=profile,
        status=ViolationReport.Status.PENDING,
    ).first()
    form = ViolationForm(reason_choices=ViolationReport.Reason.choices)
    if request.method == "POST" and existing is None:
        form = ViolationForm(request.POST, reason_choices=ViolationReport.Reason.choices)
        if form.is_valid():
            ViolationReport.objects.create(
                reporter=request.user,
                profile=profile,
                reason=form.cleaned_data["reason"],
                body=form.cleaned_data["body"],
            )
            messages.success(request, "گزارش تخلف ثبت شد و دست مدیر است.")
            return redirect("profile", pk)
    return render(
        request,
        "talent/report_profile.html",
        {"profile": profile, "form": form, "existing": existing},
    )


@staff_member_required(login_url="login")
def support_desk(request):
    if request.method == "POST":
        kind = request.POST.get("kind")
        action = request.POST.get("action")
        item_id = request.POST.get("id")
        if kind == "ticket" and str(item_id).isdigit():
            ticket = Ticket.objects.filter(pk=int(item_id)).first()
            if ticket and action == "reply":
                reply = (request.POST.get("reply") or "").strip()
                if not reply:
                    messages.error(request, "پاسخ تیکت خالی است.")
                else:
                    ticket.reply = reply
                    ticket.status = Ticket.Status.ANSWERED
                    ticket.replied_at = timezone.now()
                    ticket.save(update_fields=["reply", "status", "replied_at"])
                    messages.success(request, "پاسخ تیکت ثبت شد.")
            elif ticket and action == "close":
                ticket.status = Ticket.Status.CLOSED
                ticket.save(update_fields=["status"])
                messages.success(request, "تیکت بسته شد.")
        elif kind == "violation" and str(item_id).isdigit():
            report = ViolationReport.objects.filter(
                pk=int(item_id),
                status=ViolationReport.Status.PENDING,
            ).first()
            if report and action == "review":
                report.status = ViolationReport.Status.REVIEWED
                report.reviewed_at = timezone.now()
                report.save(update_fields=["status", "reviewed_at"])
                messages.success(request, "گزارش تخلف رسیدگی شد.")
            elif report and action == "dismiss":
                report.status = ViolationReport.Status.DISMISSED
                report.reviewed_at = timezone.now()
                report.save(update_fields=["status", "reviewed_at"])
                messages.success(request, "گزارش تخلف رد شد.")
        return redirect("support")
    return render(
        request,
        "talent/support.html",
        {
            "open_tickets": Ticket.objects.filter(status=Ticket.Status.OPEN).select_related(
                "author__profile"
            ),
            "recent_tickets": Ticket.objects.exclude(status=Ticket.Status.OPEN).select_related(
                "author__profile"
            )[:8],
            "pending_reports": ViolationReport.objects.filter(
                status=ViolationReport.Status.PENDING
            ).select_related("reporter__profile", "profile", "job"),
        },
    )


@login_required
@require_POST
def push_subscribe(request):
    try:
        payload = json.loads(request.body.decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False}, status=400)
    endpoint = str(payload.get("endpoint") or "").strip()
    keys = payload.get("keys") if isinstance(payload.get("keys"), dict) else {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if (
        not endpoint.startswith("https://")
        or len(endpoint) > 2000
        or not p256dh
        or len(p256dh) > 255
        or not auth
        or len(auth) > 255
    ):
        return JsonResponse({"ok": False}, status=400)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": request.user, "p256dh": p256dh, "auth": auth},
    )
    return JsonResponse({"ok": True})


@login_required
def message_ping(request):
    user = request.user
    unread = (
        Message.objects.filter(read_at__isnull=True, status="approved")
        .exclude(sender=user)
        .filter(Q(thread__user_low=user) | Q(thread__user_high=user))
        .select_related("sender__profile")
        .order_by("-id")
    )
    latest = unread.first()
    name = ""
    preview = ""
    url = ""
    latest_id = 0
    if latest is not None:
        profile = getattr(latest.sender, "profile", None)
        name = profile.display_name if profile and profile.display_name else latest.sender.username
        preview = " ".join(latest.body.split())[:80]
        url = reverse("thread", args=[latest.thread_id])
        latest_id = latest.id
    response = JsonResponse(
        {
            "count": unread.count(),
            "latest_id": latest_id,
            "name": name,
            "preview": preview,
            "url": url,
        }
    )
    response["Cache-Control"] = "no-store"
    return response


@login_required
def inbox(request):
    user = request.user
    latest = Message.objects.filter(thread=OuterRef("pk")).filter(
        Q(status="approved") | Q(sender=user)
    ).order_by("-id")
    unread = Message.objects.filter(
        thread=OuterRef("pk"),
        read_at__isnull=True,
        status="approved",
    ).exclude(sender=user)
    threads = (
        Thread.objects.filter(Q(user_low=user) | Q(user_high=user))
        .select_related("user_low__profile", "user_high__profile")
        .annotate(
            last_body=Subquery(latest.values("body")[:1]),
            last_at=Subquery(latest.values("created_at")[:1]),
            has_unread=Exists(unread),
        )
        .order_by("-last_at", "-id")
    )
    return render(request, "talent/inbox.html", {"threads": threads})


@login_required
def thread_detail(request, pk):
    thread = get_object_or_404(
        Thread.objects.select_related("user_low__profile", "user_high__profile"),
        pk=pk,
    )
    if not thread.involves(request.user):
        messages.error(request, "این گفتگو برای شما نیست.")
        return redirect("inbox")
    form = MessageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not account_can_message(request):
            return redirect("thread", pk)
        Message.objects.create(
            thread=thread,
            sender=request.user,
            body=form.cleaned_data["body"],
            status="pending",
        )
        messages.success(request, "پیام ثبت شد. بعد از تایید مدیر یا پشتیبان به طرف مقابل می‌رسد.")
        return redirect("thread", pk)
    Message.objects.filter(
        thread=thread,
        read_at__isnull=True,
        status="approved",
    ).exclude(sender=request.user).update(read_at=timezone.now())
    other = thread.counterpart(request.user)
    return render(
        request,
        "talent/thread.html",
        {
            "thread": thread,
            "other": other,
            "form": form,
            "messages_list": visible_messages(thread, request.user),
        },
    )


def banner_day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


def banner_period(request):
    today = timezone.localdate()
    preset = request.GET.get("range", "7")
    start = today - timedelta(days=6)
    end = today
    if preset == "today":
        start = today
    elif preset == "30":
        start = today - timedelta(days=29)
    elif preset == "90":
        start = today - timedelta(days=89)
    elif preset == "custom":
        parsed_start = _parse_report_date(request.GET.get("start"))
        parsed_end = _parse_report_date(request.GET.get("end"))
        start = parsed_start or start
        end = parsed_end or end
        if start > end:
            start, end = end, start
    else:
        preset = "7"
    return preset, start, end


def _parse_report_date(value):
    return parse_day(value)


def banner_place_label(banner):
    if banner.place == Banner.Place.SECTION and banner.category_id:
        return f"دسته {banner.category.name}"
    if banner.place == Banner.Place.BLOG:
        return "بلاگ"
    return "صفحه اول"


def blog_banners():
    return Banner.objects.filter(is_active=True, place=Banner.Place.BLOG).order_by("order", "id")[:2]


def banner_click_rows(start, end):
    start_dt = banner_day_start(start)
    end_dt = banner_day_start(end + timedelta(days=1))
    click_filter = Q(clicks__clicked_at__gte=start_dt, clicks__clicked_at__lt=end_dt)
    banners = list(
        Banner.objects.select_related("category")
        .annotate(clicks_in_range=Count("clicks", filter=click_filter))
        .order_by("-clicks_in_range", "order", "id")
    )
    daily = (
        BannerClick.objects.filter(clicked_at__gte=start_dt, clicked_at__lt=end_dt)
        .annotate(day=TruncDate("clicked_at", tzinfo=timezone.get_current_timezone()))
        .values("day", "banner_id")
        .annotate(total=Count("id"))
        .order_by("day", "banner_id")
    )
    by_id = {banner.pk: banner for banner in banners}
    days = []
    for row in daily:
        banner = by_id.get(row["banner_id"])
        if banner is None or row["day"] is None:
            continue
        days.append(
            {
                "day": row["day"],
                "day_label": jalali_label(row["day"]),
                "banner": banner,
                "place": banner_place_label(banner),
                "total": row["total"],
                "total_label": persian_digits(row["total"]),
            }
        )
    for banner in banners:
        banner.clicks_label = persian_digits(banner.clicks_in_range)
        banner.place_label = banner_place_label(banner)
    return banners, days


def banner_click_csv(start, end, banners, days):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="banner-clicks.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["نوع", "از", "تا", "تاریخ", "عنوان بنر", "جا", "لینک", "تعداد کلیک"])
    start_label = jalali_label(start)
    end_label = jalali_label(end)
    for banner in banners:
        writer.writerow(
            [
                "جمع بازه",
                start_label,
                end_label,
                "",
                banner.title or "بدون عنوان",
                banner.place_label,
                banner.link,
                banner.clicks_in_range,
            ]
        )
    for row in days:
        writer.writerow(
            [
                "روزانه",
                start_label,
                end_label,
                row["day_label"],
                row["banner"].title or "بدون عنوان",
                row["place"],
                row["banner"].link,
                row["total"],
            ]
        )
    return response


def banner_go(request, pk):
    banner = get_object_or_404(Banner, pk=pk, is_active=True)
    BannerClick.objects.create(banner=banner)
    return redirect(banner.link)


@staff_member_required(login_url="login")
def banner_report(request):
    preset, start, end = banner_period(request)
    banners, days = banner_click_rows(start, end)
    if request.GET.get("export") == "csv":
        return banner_click_csv(start, end, banners, days)
    return render(
        request,
        "talent/banner_report.html",
        {
            "preset": preset,
            "start": jalali_label(start),
            "end": jalali_label(end),
            "start_label": jalali_label(start),
            "end_label": jalali_label(end),
            "banners": banners,
            "days": days,
            "total": persian_digits(sum(banner.clicks_in_range for banner in banners)),
            "unit": "کلیک",
        },
    )


def _person_name(user):
    if user is None:
        return "مهمان"
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = None
    if profile and profile.display_name:
        return profile.display_name
    return user.username


def _presence_rows():
    cutoff = online_cutoff()
    rows = []
    for item in Presence.objects.filter(last_seen__gte=cutoff).select_related("user__profile").order_by("-last_seen"):
        minutes = int((timezone.now() - item.last_seen).total_seconds() // 60)
        when = "همین حالا" if minutes < 1 else f"{persian_digits(minutes)} دقیقه پیش"
        rows.append(
            {
                "name": _person_name(item.user),
                "page": path_label(item.path),
                "when": when,
            }
        )
    return rows


def visit_rows(start, end):
    start_dt = banner_day_start(start)
    end_dt = banner_day_start(end + timedelta(days=1))
    views = PageView.objects.filter(viewed_at__gte=start_dt, viewed_at__lt=end_dt)
    daily_rows = (
        views.annotate(day=TruncDate("viewed_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(views=Count("id"), people=Count("session_key", distinct=True))
        .order_by("day")
    )
    page_rows = (
        views.values("path")
        .annotate(views=Count("id"), people=Count("session_key", distinct=True))
        .order_by("-views", "path")[:20]
    )
    days = [
        {
            "day_label": jalali_label(row["day"]),
            "views": row["views"],
            "views_label": persian_digits(row["views"]),
            "people": row["people"],
            "people_label": persian_digits(row["people"]),
        }
        for row in daily_rows
        if row["day"] is not None
    ]
    pages = [
        {
            "label": path_label(row["path"]),
            "path": row["path"],
            "views": row["views"],
            "views_label": persian_digits(row["views"]),
            "people": row["people"],
            "people_label": persian_digits(row["people"]),
        }
        for row in page_rows
    ]
    totals = views.aggregate(views=Count("id"), people=Count("session_key", distinct=True))
    return totals["views"] or 0, totals["people"] or 0, days, pages


def visit_csv(start, end, view_count, people_count, days, pages):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="site-visits.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["نوع", "از", "تا", "تاریخ", "مسیر", "بازدید", "نفر"])
    start_label = jalali_label(start)
    end_label = jalali_label(end)
    writer.writerow(["جمع بازه", start_label, end_label, "", "کل سایت", view_count, people_count])
    for row in days:
        writer.writerow(["روزانه", start_label, end_label, row["day_label"], "", row["views"], row["people"]])
    for row in pages:
        writer.writerow(["صفحه", start_label, end_label, "", row["label"], row["views"], row["people"]])
    return response


@staff_member_required(login_url="login")
def support_report(request):
    if not request.user.is_superuser:
        messages.error(request, "گزارش کارکرد پشتیبان فقط برای مدیر است.")
        return redirect("desk")
    supporters = (
        Profile.objects.filter(is_support=True)
        .select_related("user", "access")
        .order_by("display_name", "id")
    )
    logs = StaffLog.objects.select_related("user__profile")
    who = request.GET.get("who", "")
    if who.isdigit():
        logs = logs.filter(user_id=int(who))
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="support-log.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["نام", "شماره", "کار", "مسیر", "زمان"])
        for row in logs[:2000]:
            profile = getattr(row.user, "profile", None)
            writer.writerow(
                [
                    profile.display_name if profile else row.user.username,
                    profile.phone if profile else "",
                    row.summary,
                    row.path,
                    jalali_datetime(timezone.localtime(row.created_at)),
                ]
            )
        return response
    cards = []
    for profile in supporters:
        try:
            access = profile.access
            labels = access.labels() or ["هیچ بخشی"]
        except SupportAccess.DoesNotExist:
            labels = ["همه بخش‌ها"]
        last = StaffLog.objects.filter(user=profile.user).first()
        cards.append(
            {
                "profile": profile,
                "labels": labels,
                "count": StaffLog.objects.filter(user=profile.user).count(),
                "last": last,
            }
        )
    return render(
        request,
        "talent/support_report.html",
        {"cards": cards, "logs": logs[:80], "supporters": supporters, "who": who},
    )


@staff_member_required(login_url="login")
def reports(request):
    today = banner_day_start(timezone.localdate())
    today_views = PageView.objects.filter(viewed_at__gte=today)
    online = _presence_rows()
    return render(
        request,
        "talent/reports.html",
        {
            "online": online,
            "online_count": persian_digits(len(online)),
            "online_minutes": persian_digits(ONLINE_MINUTES),
            "views_today": persian_digits(today_views.count()),
            "people_today": persian_digits(today_views.values("session_key").distinct().count()),
        },
    )


@staff_member_required(login_url="login")
def visit_report(request):
    preset, start, end = banner_period(request)
    view_count, people_count, days, pages = visit_rows(start, end)
    if request.GET.get("export") == "csv":
        return visit_csv(start, end, view_count, people_count, days, pages)
    online = _presence_rows()
    return render(
        request,
        "talent/visit_report.html",
        {
            "preset": preset,
            "start": jalali_label(start),
            "end": jalali_label(end),
            "start_label": jalali_label(start),
            "end_label": jalali_label(end),
            "days": days,
            "pages": pages,
            "total": persian_digits(view_count),
            "people": persian_digits(people_count),
            "unit": "بازدید",
            "online": online,
            "online_count": persian_digits(len(online)),
            "online_minutes": persian_digits(ONLINE_MINUTES),
        },
    )


@staff_member_required(login_url="login")
@require_POST
def delete_banner(request, pk):
    Banner.objects.filter(pk=pk).delete()
    messages.success(request, "بنر حذف شد.")
    return redirect("banners")


def banner_place_label(banner):
    if banner.place == Banner.Place.BLOG:
        return "بلاگ"
    if banner.place == Banner.Place.SECTION and banner.category_id:
        names = []
        node = banner.category
        guard = 0
        while node is not None and guard < 6:
            names.append(node.name)
            node = node.parent if node.parent_id else None
            guard += 1
        return " / ".join(reversed(names))
    return "صفحه اول"


def banner_groups(banners):
    home = [banner for banner in banners if banner.place == Banner.Place.HOME]
    blog = [banner for banner in banners if banner.place == Banner.Place.BLOG]
    by_category = {}
    for banner in banners:
        if banner.place == Banner.Place.SECTION:
            by_category.setdefault(banner.category_id, []).append(banner)
    groups = []
    if home:
        groups.append({"title": "صفحه اول", "banners": home})
    if blog:
        groups.append({"title": "بلاگ", "banners": blog})
    seen = set()

    def walk(category):
        items = by_category.get(category.id)
        if items:
            groups.append({"title": str(category), "banners": items})
            seen.add(category.id)
        for child in category.children.all():
            walk(child)

    roots = Category.objects.filter(parent__isnull=True).prefetch_related(
        "children__children__children"
    )
    for root in roots:
        walk(root)
    for category_id, items in by_category.items():
        if category_id not in seen and items:
            groups.append({"title": items[0].where, "banners": items})
    return groups


@staff_member_required(login_url="login")
def banners(request):
    form = BannerForm()
    edit_form = None
    edit_id = None
    if request.method == "POST" and request.POST.get("form") == "edit":
        banner = get_object_or_404(Banner, pk=request.POST.get("id"))
        edit_id = banner.pk
        edit_form = BannerForm(request.POST, request.FILES, instance=banner)
        if "image" not in request.FILES:
            edit_form.fields["image"].required = False
        if edit_form.is_valid():
            edit_form.save()
            messages.success(request, "بنر ذخیره شد.")
            return redirect("banners")
    elif request.method == "POST":
        form = BannerForm(request.POST, request.FILES)
        if form.is_valid():
            banner = form.save(commit=False)
            if banner.place == Banner.Place.SECTION:
                banner.order = Banner.objects.filter(
                    place=Banner.Place.SECTION, category=banner.category
                ).count()
            elif banner.place == Banner.Place.BLOG:
                banner.order = Banner.objects.filter(place=Banner.Place.BLOG).count()
            else:
                banner.order = Banner.objects.filter(place=Banner.Place.HOME).count()
            banner.save()
            if banner.place == Banner.Place.SECTION:
                messages.success(request, "بنر کوچک ذخیره شد و داخل همان دسته، کنار بنر دیگر دیده می‌شود.")
            elif banner.place == Banner.Place.BLOG:
                messages.success(request, "بنر بلاگ ذخیره شد و کنار بنر دیگر در بلاگ دیده می‌شود.")
            else:
                messages.success(request, "بنر صفحه اول اضافه شد و با دو بنر دیگر می‌چرخد.")
            return redirect("banners")
    banners = list(
        Banner.objects.select_related("category__parent__parent__parent").annotate(
            clicks_today=Count("clicks", filter=Q(clicks__clicked_at__gte=banner_day_start(timezone.localdate()))),
            clicks_week=Count(
                "clicks",
                filter=Q(clicks__clicked_at__gte=banner_day_start(timezone.localdate() - timedelta(days=6))),
            ),
            clicks_month=Count(
                "clicks",
                filter=Q(clicks__clicked_at__gte=banner_day_start(timezone.localdate() - timedelta(days=29))),
            ),
        )
    )
    for banner in banners:
        banner.where = banner_place_label(banner)
    home_count = sum(banner.place == Banner.Place.HOME for banner in banners)
    blog_count = sum(banner.place == Banner.Place.BLOG for banner in banners)
    banner_left = sum((banner.title or "").strip() == "جای تبلیغ شما" for banner in banners)
    banner_total = len(banners)
    banner_filled = banner_total - banner_left
    return render(
        request,
        "talent/banners.html",
        {
            "form": form,
            "edit_form": edit_form,
            "edit_id": edit_id,
            "banner_groups": banner_groups(banners),
            "home_count": home_count,
            "blog_count": blog_count,
            "banner_limit": 3,
            "banner_total": banner_total,
            "banner_filled": banner_filled,
            "banner_left": banner_total - banner_filled,
        },
    )


@staff_member_required(login_url="login")
def manage_jobs(request):
    if not can(request.user, "moderate"):
        messages.error(request, "این بخش برای تو باز نیست.")
        return redirect("desk")
    JobPost.purge_expired()
    kind = request.GET.get("kind", "").strip()
    if kind not in (JobPost.Kind.HIRE, JobPost.Kind.SEEK):
        kind = ""
    edit_post = None
    edit_form = None
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        raw_id = (request.POST.get("id") or "").strip()
        post = JobPost.objects.filter(pk=int(raw_id)).first() if raw_id.isdigit() else None
        if post is None:
            messages.error(request, "این آگهی پیدا نشد.")
            return redirect("manage_jobs")
        if action == "delete":
            post.delete()
            messages.success(request, "آگهی حذف شد.")
            return redirect("manage_jobs")
        if action == "save":
            edit_form = JobForm(request.POST, instance=post)
            if edit_form.is_valid():
                saved = edit_form.save(commit=False)
                if saved.status == JobPost.Status.APPROVED:
                    start = saved.reviewed_at or timezone.now()
                    saved.expires_at = start + timedelta(days=saved.duration_days)
                saved.save()
                messages.success(request, "آگهی ویرایش شد.")
                return redirect("manage_jobs")
            edit_post = post
        else:
            messages.error(request, "این کار پیدا نشد.")
            return redirect("manage_jobs")
    if edit_post is None:
        raw_edit = (request.GET.get("edit") or "").strip()
        if raw_edit.isdigit():
            edit_post = JobPost.objects.filter(pk=int(raw_edit)).select_related("author__profile").first()
            if edit_post is not None:
                edit_form = JobForm(instance=edit_post)
    posts = JobPost.objects.select_related("author__profile", "category")
    hire_count = posts.filter(kind=JobPost.Kind.HIRE).count()
    seek_count = posts.filter(kind=JobPost.Kind.SEEK).count()
    if kind:
        posts = posts.filter(kind=kind)
    return render(
        request,
        "talent/manage_jobs.html",
        {
            "posts": stamp_job_views(posts, request.user),
            "kind": kind,
            "hire_count": hire_count,
            "seek_count": seek_count,
            "edit_post": edit_post,
            "edit_form": edit_form,
        },
    )


def jobs(request):
    kind = request.GET.get("kind", "").strip()
    q = request.GET.get("q", "").strip()
    posts = JobPost.visible().select_related(
        "author__profile", "category", "category__parent"
    )
    if kind in (JobPost.Kind.HIRE, JobPost.Kind.SEEK):
        posts = posts.filter(kind=kind)
    if q:
        posts = posts.filter(
            Q(title__icontains=q)
            | Q(body__icontains=q)
            | Q(city__icontains=q)
            | Q(category__name__icontains=q)
            | Q(author__profile__display_name__icontains=q)
        )
    form = JobForm()
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next=/jobs/")
        profile = profile_for(request.user)
        if not request.user.is_staff and profile.account_status != "approved":
            messages.error(request, "تا تایید ثبت‌نام، ثبت آگهی باز نیست.")
            return redirect("jobs")
        form = JobForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.status = JobPost.Status.PENDING
            post.save()
            messages.success(request, "آگهی ثبت شد. بعد از تایید مدیر یا پشتیبان در فهرست دیده می‌شود.")
            return redirect("jobs")
    mine = []
    if request.user.is_authenticated:
        mine = stamp_job_views(
            JobPost.objects.filter(author=request.user).select_related("category"),
            request.user,
        )
    return render(
        request,
        "talent/jobs.html",
        {
            "posts": stamp_job_views(posts, request.user),
            "mine": mine,
            "form": form,
            "kind": kind,
            "query": q,
            "seo": jobs_page(request),
        },
    )


def job_detail(request, pk):
    JobPost.purge_expired()
    post = get_object_or_404(
        JobPost.objects.select_related("author__profile", "category", "category__parent"),
        pk=pk,
    )
    owner = request.user.is_authenticated and request.user.id == post.author_id
    staff = request.user.is_authenticated and request.user.is_staff
    visible = (
        post.status == JobPost.Status.APPROVED
        and post.expires_at is not None
        and post.expires_at > timezone.now()
    )
    if not visible and not owner and not staff:
        raise Http404("این آگهی الان دیده نمی‌شود.")
    stamp_job_views([post], request.user)
    return render(
        request,
        "talent/job_detail.html",
        {
            "post": post,
            "owner": owner,
            "job_warning": job_warning_text(),
            "item_saved": bookmark_saved(request.user, Bookmark.Kind.JOB, post.pk),
        },
    )


@login_required
def report_job(request, pk):
    post = get_object_or_404(
        JobPost.objects.select_related("author__profile"),
        pk=pk,
    )
    visible = (
        post.status == JobPost.Status.APPROVED
        and post.expires_at is not None
        and post.expires_at > timezone.now()
    )
    if post.author_id == request.user.id:
        messages.error(request, "گزارش تخلف برای آگهی خودت ثبت نمی‌شود.")
        return redirect("job_detail", pk)
    if not visible and not request.user.is_staff:
        raise Http404("این آگهی الان دیده نمی‌شود.")
    existing = ViolationReport.objects.filter(
        reporter=request.user,
        job=post,
        status=ViolationReport.Status.PENDING,
    ).first()
    form = ViolationForm(reason_choices=ViolationReport.Reason.choices)
    if request.method == "POST" and existing is None:
        form = ViolationForm(request.POST, reason_choices=ViolationReport.Reason.choices)
        if form.is_valid():
            ViolationReport.objects.create(
                reporter=request.user,
                profile=post.author.profile,
                job=post,
                reason=form.cleaned_data["reason"],
                body=form.cleaned_data["body"],
            )
            messages.success(request, "گزارش تخلف ثبت شد و دست مدیر است.")
            return redirect("job_detail", pk)
    return render(
        request,
        "talent/report_job.html",
        {"post": post, "form": form, "existing": existing},
    )


@login_required
@require_POST
def delete_job(request, pk):
    JobPost.objects.filter(pk=pk, author=request.user).delete()
    messages.success(request, "آگهی حذف شد.")
    return redirect("jobs")


@staff_member_required(login_url="login")
def categories_board(request):
    subcategory_form = SubcategoryForm()
    new_category_form = NewCategoryForm()
    if request.method == "POST":
        kind = request.POST.get("form")
        if kind == "new_category":
            new_category_form = NewCategoryForm(request.POST)
            if new_category_form.is_valid():
                Category.objects.create(name=new_category_form.cleaned_data["name"], parent=None)
                messages.success(request, "دسته جدید اضافه شد و در فهرست دیده می‌شود.")
                return redirect("categories")
        elif kind == "category":
            subcategory_form = SubcategoryForm(request.POST)
            if subcategory_form.is_valid():
                Category.objects.create(
                    name=subcategory_form.cleaned_data["name"],
                    parent=subcategory_form.cleaned_data["parent"],
                )
                messages.success(request, "زیرمجموعه اضافه شد و در فهرست و جستجو دیده می‌شود.")
                return redirect("categories")
        elif kind == "category_edit":
            category = get_object_or_404(Category, pk=request.POST.get("id"))
            name = (request.POST.get("name") or "").strip()
            if not name:
                messages.error(request, "نام دسته را بنویس.")
            elif Category.objects.filter(name=name, parent=category.parent).exclude(pk=category.pk).exists():
                messages.error(request, "این نام در همین سطح هست.")
            else:
                category.name = name
                category.save(update_fields=["name"])
                messages.success(request, "نام دسته عوض شد.")
            return redirect("categories")
        elif kind == "category_seo":
            category = get_object_or_404(Category, pk=request.POST.get("id"))
            title, description, error = clean_seo_pair(request.POST)
            if error:
                messages.error(request, error)
            else:
                category.seo_title = title
                category.seo_description = description
                category.save(update_fields=["seo_title", "seo_description"])
                messages.success(request, "سئوی این دسته ذخیره شد.")
            return redirect("categories")
        elif kind == "category_delete":
            category = get_object_or_404(Category, pk=request.POST.get("id"))
            if category.children.exists():
                messages.error(request, "این دسته زیرمجموعه دارد. اول زیرمجموعه‌ها را حذف کن.")
            else:
                category.delete()
                messages.success(request, "دسته حذف شد.")
            return redirect("categories")
    def pack(category):
        attach_audit(category, name=category.name)
        return {"category": category, "children": [pack(child) for child in category.children.all()]}

    tree = [
        pack(category)
        for category in Category.objects.filter(parent__isnull=True).prefetch_related(
            "children__children"
        )
    ]
    return render(
        request,
        "talent/categories.html",
        {
            "subcategory_form": subcategory_form,
            "new_category_form": new_category_form,
            "tree": tree,
        },
    )


@staff_member_required(login_url="login")
def desk(request):
    note = WelcomeMessage.objects.order_by("pk").first()
    welcome_form = WelcomeForm(note=note)
    if request.method == "POST" and request.POST.get("form") == "welcome":
        welcome_form = WelcomeForm(request.POST, request.FILES, note=note)
        if welcome_form.is_valid():
            save_welcome(welcome_form)
            messages.success(request, "پیام خوش‌آمد ذخیره شد.")
            return redirect("desk")
    elif request.method == "POST" and request.POST.get("form") == "page_seo":
        if not request.user.is_superuser:
            messages.error(request, "سئوی صفحه‌های ثابت فقط برای مدیر است.")
            return redirect("desk")
        key = (request.POST.get("id") or "").strip()
        if key not in PageSeo.Key.values:
            messages.error(request, "این صفحه پیدا نشد.")
            return redirect("desk")
        title, description, error = clean_seo_pair(request.POST)
        if error:
            messages.error(request, error)
        else:
            row, _created = PageSeo.objects.get_or_create(key=key)
            row.seo_title = title
            row.seo_description = description
            row.save(update_fields=["seo_title", "seo_description"])
            messages.success(request, "سئوی صفحه ذخیره شد.")
        return redirect("desk")
    elif request.method == "POST" and request.POST.get("form") == "home_copy":
        if not request.user.is_superuser:
            messages.error(request, "نوشته‌های صفحه اصلی فقط برای مدیر است.")
            return redirect("desk")
        save_home_lines(request.POST)
        messages.success(request, "نوشته‌های صفحه اصلی ذخیره شد.")
        return redirect("desk")
    elif request.method == "POST" and request.POST.get("form") == "job_warning":
        if not request.user.is_superuser:
            messages.error(request, "متن زنگ خطر فقط برای مدیر است.")
            return redirect("desk")
        save_job_warning(request.POST)
        messages.success(request, "زنگ خطر قبل از همکاری ذخیره شد.")
        return redirect("desk")
    return render(
        request,
        "talent/desk.html",
        {
            "counts": {
                "signup": Profile.objects.filter(account_status="pending").count(),
                "role": ProfileRole.objects.filter(status=ProfileRole.Status.PENDING).count(),
                "message": Message.objects.filter(status="pending").count(),
                "job": JobPost.objects.filter(status=JobPost.Status.PENDING).count(),
                "job_board": JobPost.objects.count(),
                "phone": PhoneRequest.objects.filter(status=PhoneRequest.Status.PENDING).count(),
                "identity": IdentityDocument.objects.filter(status=IdentityDocument.Status.PENDING).count(),
            },
            "listed": public_profiles().count(),
            "user_count": Profile.objects.exclude(user__is_staff=True).count(),
            "welcome_form": welcome_form,
            "welcome_note": note,
            "page_seo": page_seo_rows() if request.user.is_superuser else [],
            "home_fields": home_fields() if request.user.is_superuser else [],
            "job_warning": job_warning_text() if request.user.is_superuser else "",
        },
    )


def _apply_support_permissions(profile, chosen):
    access, _created = SupportAccess.objects.get_or_create(profile=profile)
    for code, _label in PERMISSIONS:
        setattr(access, code, code in chosen)
    access.save()
    return access


def _supporter_rows():
    rows = []
    for profile in (
        Profile.objects.filter(is_support=True, user__is_superuser=False)
        .select_related("user", "access")
        .order_by("display_name", "id")
    ):
        profile.perm_rows = rows_for(profile)
        rows.append(profile)
    return rows


@staff_member_required(login_url="login")
def supporters(request):
    if not request.user.is_superuser:
        messages.error(request, "تعریف پشتیبان فقط برای مدیر است.")
        return redirect("desk")
    form = SupportAccountForm()
    edit_id = ""
    edit_form = None
    if request.method == "POST":
        kind = request.POST.get("kind")
        item_id = request.POST.get("id")
        chosen = set(request.POST.getlist("perm"))
        if kind == "create-support":
            form = SupportAccountForm(request.POST)
            ready = form.is_valid()
            if ready and not chosen:
                form.add_error(None, "حداقل یک دسترسی را انتخاب کن.")
                ready = False
            if ready:
                phone = form.cleaned_data["phone"]
                try:
                    with transaction.atomic():
                        user = User(username=phone, is_staff=True)
                        user.set_unusable_password()
                        user.save()
                        profile = profile_for(user)
                        profile.phone = phone
                        profile.display_name = form.cleaned_data["display_name"]
                        profile.account_status = "approved"
                        profile.accepted_terms_at = timezone.now()
                        profile.is_support = True
                        profile.save()
                        _apply_support_permissions(profile, chosen)
                except IntegrityError:
                    form.add_error("phone", "این شماره قبلاً ثبت شده.")
                else:
                    messages.success(
                        request,
                        "پشتیبان ساخته شد. با همین شماره و کد پیامکی وارد می‌شود و فقط بخش‌های انتخاب‌شده را می‌بیند.",
                    )
                    return redirect("supporters")
        elif kind == "edit-support" and str(item_id).isdigit():
            profile = (
                Profile.objects.filter(pk=int(item_id), is_support=True)
                .select_related("user")
                .first()
            )
            if profile is None or profile.user.is_superuser:
                messages.error(request, "این پشتیبان را نمی‌توان ویرایش کرد.")
                return redirect("supporters")
            edit_form = SupportAccountForm(request.POST, user=profile.user)
            ready = edit_form.is_valid()
            if ready and not chosen:
                edit_form.add_error(None, "حداقل یک دسترسی را انتخاب کن.")
                ready = False
            if ready:
                phone = edit_form.cleaned_data["phone"]
                old_phone = profile.phone
                try:
                    with transaction.atomic():
                        profile.phone = phone
                        profile.display_name = edit_form.cleaned_data["display_name"]
                        profile.save(update_fields=["phone", "display_name"])
                        if profile.user.username == old_phone:
                            profile.user.username = phone
                            profile.user.save(update_fields=["username"])
                        _apply_support_permissions(profile, chosen)
                except IntegrityError:
                    edit_form.add_error("phone", "این شماره قبلاً ثبت شده.")
                else:
                    messages.success(request, "پشتیبان ویرایش شد.")
                    return redirect("supporters")
            edit_id = str(profile.pk)
        elif kind == "delete-support" and str(item_id).isdigit():
            profile = (
                Profile.objects.filter(pk=int(item_id), is_support=True)
                .select_related("user")
                .first()
            )
            if profile is None or profile.user_id == request.user.id or profile.user.is_superuser:
                messages.error(request, "این پشتیبان را نمی‌توان حذف کرد.")
            else:
                profile.user.delete()
                messages.success(request, "پشتیبان و حسابش پاک شد.")
            return redirect("supporters")
    return render(
        request,
        "talent/supporters.html",
        {
            "form": form,
            "edit_form": edit_form,
            "edit_id": edit_id,
            "permissions": PERMISSIONS,
            "supporters": _supporter_rows(),
        },
    )


@staff_member_required(login_url="login")
def moderation(request):
    JobPost.purge_expired()
    create_form = StaffUserForm()
    if request.method == "POST":
        kind = request.POST.get("kind")
        action = request.POST.get("action")
        item_id = request.POST.get("id")
        new_status = "approved" if action == "approve" else "rejected"
        if kind == "create-user":
            create_form = StaffUserForm(request.POST)
            if create_form.is_valid():
                phone = create_form.cleaned_data["phone"]
                try:
                    with transaction.atomic():
                        user = User(username=phone)
                        user.set_unusable_password()
                        user.save()
                        profile = profile_for(user)
                        profile.phone = phone
                        profile.display_name = create_form.cleaned_data["display_name"]
                        profile.city = create_form.cleaned_data["city"]
                        profile.account_status = "approved"
                        profile.accepted_terms_at = timezone.now()
                        profile.save()
                        ProfileRole.objects.bulk_create(
                            [
                                ProfileRole(
                                    profile=profile,
                                    role=role,
                                    status=ProfileRole.Status.APPROVED,
                                )
                                for role in create_form.cleaned_data["roles"]
                            ]
                        )
                except IntegrityError:
                    create_form.add_error("phone", "این شماره قبلاً ثبت شده.")
                else:
                    messages.success(
                        request,
                        "حساب ساخته شد و تایید است. این شخص با همین شماره و کد پیامکی وارد می‌شود.",
                    )
                    return redirect("moderation")
            return render(request, "talent/moderation.html", _moderation_context(request, create_form))
        if kind == "role" and str(item_id).isdigit():
            ProfileRole.objects.filter(pk=int(item_id)).update(status=new_status)
            messages.success(request, "نقش بررسی شد.")
        elif kind == "role-user" and str(item_id).isdigit() and action == "approve":
            profile = Profile.objects.filter(pk=int(item_id)).first()
            if profile is None:
                messages.error(request, "این کاربر پیدا نشد.")
            else:
                ProfileRole.objects.filter(
                    profile=profile,
                    status=ProfileRole.Status.PENDING,
                ).update(status=ProfileRole.Status.APPROVED)
                if profile.account_status == "pending" and profile.user_id != request.user.id:
                    profile.account_status = "approved"
                    profile.rejection_note = ""
                    profile.save(update_fields=["account_status", "rejection_note"])
                    messages.success(request, "ثبت‌نام و تخصص‌های این کاربر تایید شد.")
                else:
                    messages.success(request, "تخصص‌های این کاربر تایید شد.")
        elif kind == "phone" and str(item_id).isdigit():
            PhoneRequest.objects.filter(pk=int(item_id)).update(
                status=new_status,
                reviewed_at=timezone.now(),
            )
            messages.success(request, "درخواست شماره بررسی شد.")
        elif kind == "charge" and str(item_id).isdigit():
            if action == "approve" and approve_charge(int(item_id)):
                charge = ChargeRequest.objects.filter(pk=int(item_id)).select_related("user").first()
                if charge and buy_year(charge.user):
                    messages.success(request, "شارژ تایید شد و صفحه برای یک سال در جستجو باز شد.")
                else:
                    messages.success(request, "شارژ به کیف پول اضافه شد. هنوز به قیمت یک سال نرسیده است.")
            elif action != "approve":
                updated = ChargeRequest.objects.filter(
                    pk=int(item_id),
                    status=ChargeRequest.Status.PENDING,
                ).update(status=ChargeRequest.Status.REJECTED, reviewed_at=timezone.now())
                if updated:
                    messages.success(request, "درخواست شارژ رد شد.")
        elif kind == "signup" and str(item_id).isdigit():
            profile = Profile.objects.filter(pk=int(item_id)).exclude(user=request.user).first()
            if profile is None:
                messages.error(request, "این ثبت‌نام را نمی‌توان بررسی کرد.")
            elif action == "approve":
                profile.account_status = "approved"
                profile.rejection_note = ""
                profile.save(update_fields=["account_status", "rejection_note"])
                messages.success(request, "ثبت‌نام تایید شد.")
            else:
                reason = (request.POST.get("reason") or "").strip()
                if not reason:
                    messages.error(request, "برای رد کردن، دلیل را بنویس. کاربر همان دلیل را می‌بیند.")
                else:
                    profile.account_status = "rejected"
                    profile.rejection_note = reason[:500]
                    profile.save(update_fields=["account_status", "rejection_note"])
                    messages.success(request, "ثبت‌نام رد شد و دلیل برای کاربر ماند.")
        elif kind == "job" and str(item_id).isdigit():
            post = JobPost.objects.filter(pk=int(item_id), status=JobPost.Status.PENDING).first()
            if post and action == "approve":
                now = timezone.now()
                post.status = JobPost.Status.APPROVED
                post.reviewed_at = now
                post.expires_at = now + timedelta(days=post.duration_days)
                post.save(update_fields=["status", "reviewed_at", "expires_at"])
                messages.success(request, "آگهی کار تایید شد.")
            elif post:
                post.status = JobPost.Status.REJECTED
                post.reviewed_at = timezone.now()
                post.save(update_fields=["status", "reviewed_at"])
                messages.success(request, "آگهی کار رد شد.")
        elif kind == "message" and str(item_id).isdigit():
            message = (
                Message.objects.filter(pk=int(item_id), status="pending")
                .select_related("sender__profile", "thread")
                .first()
            )
            if message is not None:
                message.status = new_status
                message.reviewed_at = timezone.now()
                message.save(update_fields=["status", "reviewed_at"])
                if new_status == "approved":
                    notify_message(message)
                messages.success(request, "پیام بررسی شد.")
        elif kind == "identity" and str(item_id).isdigit():
            document = IdentityDocument.objects.filter(pk=int(item_id)).select_related("profile").first()
            if document and action == "revoke":
                document.profile.is_vip = False
                document.profile.save(update_fields=["is_vip"])
                messages.success(request, "نشان VIP برداشته شد.")
            elif document and action == "approve":
                document.status = IdentityDocument.Status.APPROVED
                document.reviewed_at = timezone.now()
                document.save(update_fields=["status", "reviewed_at"])
                profile = document.profile
                profile.is_vip = True
                update_fields = ["is_vip"]
                score = (request.POST.get("staff_score") or "").strip()
                if score.isdigit() and 1 <= int(score) <= 5:
                    profile.staff_score = int(score)
                    update_fields.append("staff_score")
                profile.save(update_fields=update_fields)
                messages.success(request, "مدرک تایید شد و کنار نام، VIP نشست.")
            elif document:
                document.status = IdentityDocument.Status.REJECTED
                document.reviewed_at = timezone.now()
                document.save(update_fields=["status", "reviewed_at"])
                if not document.profile.identity_documents.filter(
                    status=IdentityDocument.Status.APPROVED
                ).exists():
                    document.profile.is_vip = False
                    document.profile.save(update_fields=["is_vip"])
                messages.success(request, "مدرک رد شد.")
        elif kind == "phone_edit" and str(item_id).isdigit():
            account = Profile.objects.filter(pk=int(item_id)).select_related("user").first()
            if account is None:
                messages.error(request, "این حساب پیدا نشد.")
            else:
                try:
                    phone = validate_phone(request.POST.get("phone", ""))
                except ValidationError as error:
                    messages.error(request, error.messages[0])
                else:
                    if phone_taken(phone, account.user):
                        messages.error(request, "این شماره برای حساب دیگری است.")
                    else:
                        account.phone = phone
                        account.save(update_fields=["phone"])
                        messages.success(request, "شماره ورود عوض شد.")
        elif kind == "account" and str(item_id).isdigit():
            profile = Profile.objects.filter(pk=int(item_id)).select_related("user").first()
            _change_account(request, profile, action)
        return redirect("moderation")
    return render(
        request,
        "talent/moderation.html",
        _moderation_context(request, create_form),
    )


def _role_groups(pending_roles, pending_signups):
    signup_ids = {profile.pk for profile in pending_signups}
    grouped = {}
    order = []
    for link in pending_roles:
        key = link.profile_id
        if key not in grouped:
            grouped[key] = {"profile": link.profile, "links": [], "signup": key in signup_ids}
            order.append(key)
        grouped[key]["links"].append(link)
    groups = []
    for key in order:
        group = grouped[key]
        group["names"] = "، ".join(link.role.name for link in group["links"])
        group["count"] = len(group["links"])
        groups.append(group)
    return groups


def _moderation_context(request, create_form):
    pending_signups = Profile.objects.filter(account_status="pending").select_related(
        "user", "recruited_by"
    )
    pending_jobs = stamp_job_views(
        JobPost.objects.filter(status=JobPost.Status.PENDING).select_related(
            "author__profile", "category"
        ),
        request.user,
    )
    pending_messages = Message.objects.filter(status="pending").select_related(
        "sender__profile", "thread__user_low__profile", "thread__user_high__profile"
    )
    pending_roles = ProfileRole.objects.filter(status=ProfileRole.Status.PENDING).select_related(
        "profile__user", "role__category"
    ).order_by("profile__display_name", "profile_id", "role__category__name", "role__name")
    pending_phones = PhoneRequest.objects.filter(status=PhoneRequest.Status.PENDING).select_related(
        "requester__profile", "profile__user"
    )
    pending_identity = IdentityDocument.objects.filter(
        status=IdentityDocument.Status.PENDING
    ).select_related("profile__user")
    role_groups = _role_groups(pending_roles, pending_signups)
    grouped_ids = {group["profile"].pk for group in role_groups}
    waiting = []
    for profile in pending_signups:
        if profile.pk in grouped_ids:
            continue
        waiting.append({
            "kind_label": "ثبت‌نام",
            "text": f"{profile.display_name or 'بدون نام'}، شماره {profile.phone or 'ندارد'}",
            "kind": "signup",
            "id": profile.pk,
            "approve_label": "تایید ثبت‌نام",
            "needs_reason": True,
        })
    for group in role_groups:
        name = group["profile"].display_name or "بدون نام"
        text = f"{name}: {group['names']}"
        if group["signup"]:
            text += " — ثبت‌نام هم منتظر است"
        waiting.append({
            "kind_label": "تخصص",
            "text": text,
            "kind": "role-user",
            "id": group["profile"].pk,
            "approve_label": "تایید همه",
            "group": group,
        })
    for item in pending_messages:
        waiting.append({
            "kind_label": "پیام",
            "text": f"از {item.sender.profile.display_name}: {item.body[:80]}",
            "kind": "message",
            "id": item.pk,
            "approve_label": "تایید پیام",
        })
    for item in pending_jobs:
        waiting.append({
            "kind_label": "آگهی کار",
            "text": f"{item.get_kind_display} — {item.title} از {item.author.profile.display_name}",
            "kind": "job",
            "id": item.pk,
            "approve_label": "تایید آگهی",
        })
    for item in pending_phones:
        waiting.append({
            "kind_label": "شماره",
            "text": f"{item.requester.profile.display_name} شماره {item.profile.display_name} را می‌خواهد",
            "kind": "phone",
            "id": item.pk,
            "approve_label": "باز کردن شماره",
        })
    for document in pending_identity:
        waiting.append({
            "kind_label": "مدرک هویت",
            "text": f"{document.profile.display_name or 'بدون نام'} — {document.label}",
            "kind": "identity",
            "id": document.pk,
            "approve_label": "تایید هویت",
            "needs_score": True,
        })
    return {
        "pending_signups": pending_signups,
        "pending_jobs": pending_jobs,
        "pending_messages": pending_messages,
        "pending_roles": pending_roles,
        "role_groups": role_groups,
        "pending_phones": pending_phones,
        "pending_identity": pending_identity,
        "pending_charges": ChargeRequest.objects.filter(
            status=ChargeRequest.Status.PENDING
        ).select_related("user__profile"),
        "waiting": waiting,
        "create_form": create_form,
    }


def _day(value):
    return parse_day(value)


def _clean_user_filters(source):
    identity = source.get("identity") or ""
    if identity not in {"yes", "no"}:
        identity = ""
    score = str(source.get("score") or "")
    if score not in {"0", "1", "2", "3", "4", "5"}:
        score = ""
    start = _day(source.get("start") or "")
    end = _day(source.get("end") or "")
    return {
        "q": (source.get("q") or "").strip(),
        "identity": identity,
        "city": (source.get("city") or "").strip(),
        "violation": "yes" if source.get("violation") == "yes" else "",
        "score": score,
        "start": jalali_label(start) if start else "",
        "end": jalali_label(end) if end else "",
    }


def _filters_from_request(request):
    if request.method == "POST":
        source = {
            "q": request.POST.get("filter_q", ""),
            "identity": request.POST.get("filter_identity", ""),
            "city": request.POST.get("filter_city", ""),
            "violation": request.POST.get("filter_violation", ""),
            "score": request.POST.get("filter_score", ""),
            "start": request.POST.get("filter_start", ""),
            "end": request.POST.get("filter_end", ""),
        }
    else:
        source = request.GET
    return _clean_user_filters(source)


def _filters_open_list(filters):
    if len(filters["q"]) >= 2:
        return True
    return any(filters[key] for key in ("identity", "city", "violation", "score", "start", "end"))


def _users_url(filters):
    if isinstance(filters, str):
        filters = {"q": filters}
    params = {key: value for key, value in filters.items() if value}
    url = reverse("system_users")
    if params:
        return f"{url}?{urlencode(params)}"
    return url


def _user_rows(query, filters=None):
    rows = (
        Profile.objects.exclude(user__is_staff=True)
        .select_related("user")
        .prefetch_related("role_links__role")
        .order_by("-created_at")
    )
    text = (query or "").strip()
    if len(text) >= 2:
        rows = rows.filter(
            Q(display_name__icontains=text)
            | Q(business_name__icontains=text)
            | Q(phone__icontains=text)
            | Q(contact_phone__icontains=text)
            | Q(city__icontains=text)
            | Q(province__icontains=text)
            | Q(address__icontains=text)
            | Q(headline__icontains=text)
            | Q(bio__icontains=text)
            | Q(about_business__icontains=text)
            | Q(seo_title__icontains=text)
            | Q(seo_description__icontains=text)
            | Q(user__username__icontains=text)
        )
    filters = filters or {}
    if filters.get("identity") == "yes":
        rows = rows.filter(is_vip=True)
    elif filters.get("identity") == "no":
        rows = rows.filter(is_vip=False)
    if filters.get("city"):
        rows = rows.filter(city=filters["city"])
    if filters.get("violation") == "yes":
        rows = rows.filter(
            Exists(
                ViolationReport.objects.filter(profile_id=OuterRef("pk")).exclude(
                    status=ViolationReport.Status.DISMISSED
                )
            )
        )
    if filters.get("score") == "0":
        rows = rows.filter(staff_score__isnull=True)
    elif filters.get("score"):
        rows = rows.filter(staff_score=int(filters["score"]))
    start = _day(filters.get("start"))
    end = _day(filters.get("end"))
    if start:
        rows = rows.filter(created_at__date__gte=start)
    if end:
        rows = rows.filter(created_at__date__lte=end)
    return rows


def _attach_money(profiles):
    user_ids = [profile.user_id for profile in profiles]
    wallets = {item.user_id: item for item in Wallet.objects.filter(user_id__in=user_ids)}
    grouped = {}
    for entry in WalletEntry.objects.filter(wallet__user_id__in=user_ids).select_related("wallet"):
        bucket = grouped.setdefault(entry.wallet.user_id, [])
        if len(bucket) >= 3:
            continue
        entry.when = jalali_label(timezone.localtime(entry.created_at).date())
        entry.amount_label = toman(abs(entry.amount))
        bucket.append(entry)
    for profile in profiles:
        wallet = wallets.get(profile.user_id)
        profile.money_label = toman(wallet.balance if wallet else 0)
        profile.money_rows = grouped.get(profile.user_id, [])
        audit = profile_audit(profile)
        profile.seo_score = audit["score"]
        profile.seo_errors = audit["errors"]
        profile.seo_notes = audit["notes"]


def _change_account(request, profile, action):
    if profile is None or profile.user_id == request.user.id or profile.user.is_staff or profile.user.is_superuser:
        messages.error(request, "این حساب را نمی‌توانی حذف یا غیرفعال کنی.")
        return False
    if action == "archive":
        profile.archived_at = timezone.now()
        profile.save(update_fields=["archived_at"])
        messages.success(request, "حساب بایگانی شد و دیگران آن را نمی‌بینند.")
    elif action == "restore":
        profile.archived_at = None
        profile.save(update_fields=["archived_at"])
        messages.success(request, "حساب از بایگانی برگشت.")
    elif action == "deactivate":
        profile.user.is_active = False
        profile.user.save(update_fields=["is_active"])
        messages.success(request, "کاربر غیرفعال شد. دیگر نمی‌تواند وارد شود و در جستجو دیده نمی‌شود.")
    elif action == "activate":
        profile.user.is_active = True
        profile.user.save(update_fields=["is_active"])
        messages.success(request, "کاربر دوباره فعال شد.")
    elif action == "delete":
        profile.user.delete()
        messages.success(request, "حساب و داده‌هایش پاک شد.")
    else:
        return False
    return True


@staff_member_required(login_url="login")
def system_users(request):
    filters = _filters_from_request(request)
    query = filters["q"]
    if request.method == "POST":
        kind = request.POST.get("kind")
        action = request.POST.get("action")
        item_id = request.POST.get("id")
        if kind == "phone_edit" and str(item_id).isdigit():
            account = Profile.objects.filter(pk=int(item_id)).exclude(user__is_staff=True).select_related("user").first()
            if account is None:
                messages.error(request, "این حساب پیدا نشد.")
            else:
                try:
                    phone = validate_phone(request.POST.get("phone", ""))
                except ValidationError as error:
                    messages.error(request, error.messages[0])
                else:
                    if phone_taken(phone, account.user):
                        messages.error(request, "این شماره برای حساب دیگری است.")
                    else:
                        account.phone = phone
                        account.save(update_fields=["phone"])
                        messages.success(request, "شماره ورود عوض شد.")
        elif kind == "edit-profile" and str(item_id).isdigit():
            _save_user_cartable(request, int(item_id))
        elif kind == "seo" and str(item_id).isdigit():
            account = Profile.objects.filter(pk=int(item_id)).exclude(user__is_staff=True).first()
            title = " ".join((request.POST.get("seo_title") or "").split())
            description = " ".join((request.POST.get("seo_description") or "").split())
            if account is None:
                messages.error(request, "این حساب پیدا نشد.")
            elif len(title) > 70:
                messages.error(request, "عنوان گوگل حداکثر ۷۰ حرف است. حدود ۵۰ تا ۶۰ حرف بنویس.")
            elif len(description) > 170:
                messages.error(request, "توضیح گوگل حداکثر ۱۷۰ حرف است. حدود ۱۲۰ تا ۱۶۰ حرف بنویس.")
            else:
                account.seo_title = title
                account.seo_description = description
                account.save(update_fields=["seo_title", "seo_description"])
                messages.success(request, "سئوی این کاربر ذخیره شد.")
        elif kind == "account" and str(item_id).isdigit():
            profile = Profile.objects.filter(pk=int(item_id)).select_related("user").first()
            _change_account(request, profile, action)
        return redirect(_users_url(filters))
    page = None
    if _filters_open_list(filters):
        page = Paginator(_user_rows(query, filters), 20).get_page(request.GET.get("page"))
        _attach_money(page.object_list)
    cities = list(
        Profile.objects.exclude(user__is_staff=True)
        .exclude(city="")
        .order_by("city")
        .values_list("city", flat=True)
        .distinct()
    )
    if filters["city"] and filters["city"] not in cities:
        cities.append(filters["city"])
    return render(
        request,
        "talent/users.html",
        {
            "query": query,
            "filters": filters,
            "filter_query": urlencode({key: value for key, value in filters.items() if value}),
            "filter_cities": cities,
            "user_total": Profile.objects.exclude(user__is_staff=True).count(),
            "page": page,
            "province_options": province_choices(),
            "city_options": city_choices(),
        },
    )


def _clip(value, limit):
    return " ".join((value or "").split())[:limit] if limit and "\n" not in (value or "") else (value or "").strip()[:limit]


def _save_user_cartable(request, profile_id):
    account = Profile.objects.filter(pk=profile_id).exclude(user__is_staff=True).first()
    if account is None:
        messages.error(request, "این حساب پیدا نشد.")
        return
    name = " ".join((request.POST.get("display_name") or "").split())
    if not name or len(name) > 80:
        messages.error(request, "نام را بنویس.")
        return
    try:
        contact = validate_contact_phone(request.POST.get("contact_phone", ""))
    except FormError as error:
        messages.error(request, error.messages[0])
        return
    city = (request.POST.get("city") or "").strip()
    known = {item for item, _province in CITIES}
    if city and city not in known:
        messages.error(request, "شهر را از فهرست انتخاب کن.")
        return
    account.display_name = name
    account.business_name = _clip(request.POST.get("business_name"), 120)
    account.headline = _clip(request.POST.get("headline"), 140)
    account.city = city
    account.province = CITY_OF.get(city) or (request.POST.get("province") or "").strip()[:80]
    account.address = (request.POST.get("address") or "").strip()[:240]
    account.contact_phone = contact
    account.bio = (request.POST.get("bio") or "").strip()
    account.about_business = (request.POST.get("about_business") or "").strip()
    account.instagram = (request.POST.get("instagram") or "").strip()[:200]
    account.telegram = (request.POST.get("telegram") or "").strip()[:200]
    account.whatsapp = (request.POST.get("whatsapp") or "").strip()[:200]
    account.website = (request.POST.get("website") or "").strip()[:200]
    account.save(
        update_fields=[
            "display_name",
            "business_name",
            "headline",
            "city",
            "province",
            "address",
            "contact_phone",
            "bio",
            "about_business",
            "instagram",
            "telegram",
            "whatsapp",
            "website",
        ]
    )
    messages.success(request, "کارتابل کاربر ذخیره شد.")


@login_required
def identity_file(request, pk):
    document = get_object_or_404(
        IdentityDocument.objects.select_related("profile__user"),
        pk=pk,
    )
    if request.user.id != document.profile.user_id and not request.user.is_staff:
        raise Http404
    if not document.file:
        raise Http404
    content_type = mimetypes.guess_type(document.file.name)[0] or "application/octet-stream"
    response = FileResponse(document.file.open("rb"), content_type=content_type)
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def wallet(request):
    account = wallet_for(request.user)
    profile = profile_for(request.user)
    form = ChargeForm()
    pending = ChargeRequest.objects.filter(
        user=request.user,
        status=ChargeRequest.Status.PENDING,
    ).first()
    if request.method == "POST":
        kind = request.POST.get("form")
        if kind == "buy":
            if buy_year(request.user):
                messages.success(request, "یک سال خریده شد. تا پایان این سال، بقیه صفحه تو را می‌بینند.")
            else:
                messages.error(request, "موجودی کیف پول برای خرید یک سال کافی نیست. اول شارژ کن.")
            return redirect("wallet")
        if kind == "charge":
            form = ChargeForm(request.POST)
            if pending:
                messages.error(request, "یک درخواست شارژ هنوز دست مدیر است.")
                return redirect("wallet")
            if form.is_valid():
                ChargeRequest.objects.create(user=request.user, amount=form.cleaned_data["amount"])
                messages.success(request, "درخواست شارژ ثبت شد. بعد از تایید مدیر، موجودی اضافه می‌شود.")
                return redirect("wallet")
    return render(
        request,
        "talent/wallet.html",
        {
            "wallet": account,
            "profile": profile,
            "form": form,
            "pending": pending,
            "price": year_price(),
            "price_label": toman(year_price()),
            "balance_label": toman(account.balance),
            "entries": account.entries.all()[:12],
        },
    )


def blog_list(request):
    categories = BlogCategory.objects.annotate(
        post_count=Count("posts", filter=Q(posts__is_published=True))
    )
    posts = Post.objects.filter(is_published=True).select_related("category")
    category_id = request.GET.get("category", "").strip()
    current = None
    if category_id.isdigit():
        current = categories.filter(pk=int(category_id)).first()
        if current:
            posts = posts.filter(category=current)
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "talent/blog_list.html",
        {
            "categories": categories,
            "current": current,
            "post_total": posts.count() if current is None else Post.objects.filter(is_published=True).count(),
            "page": Paginator(posts, 10).get_page(request.GET.get("page")),
            "querystring": params.urlencode(),
            "banners": blog_banners(),
            "seo": blog_index(request, current),
        },
    )


def blog_detail(request, pk):
    post = get_object_or_404(Post.objects.select_related("category", "author__profile"), pk=pk)
    if not post.is_published and not (request.user.is_authenticated and request.user.is_staff):
        raise Http404("نوشته پیدا نشد.")
    comments = post.comments.select_related("author__profile")
    mine = None
    if request.user.is_authenticated:
        mine = comments.filter(author=request.user).first()
    average, scored, total = post.comment_summary()
    initial = {}
    if mine:
        initial = {"score": str(mine.score) if mine.score else "", "body": mine.body}
    return render(
        request,
        "talent/blog_detail.html",
        {
            "post": post,
            "seo": blog_post(request, post),
            "more": Post.objects.filter(is_published=True, category=post.category)
            .exclude(pk=post.pk)[:4],
            "banners": blog_banners(),
            "comments": comments,
            "my_comment": mine,
            "comment_form": PostCommentForm(initial=initial),
            "average": average,
            "scored_count": scored,
            "comment_count": total,
            "item_saved": bookmark_saved(request.user, Bookmark.Kind.POST, post.pk),
        },
    )


@login_required
@require_POST
def blog_comment(request, pk):
    post = get_object_or_404(Post, pk=pk, is_published=True)
    form = PostCommentForm(request.POST)
    if form.is_valid():
        PostComment.objects.update_or_create(
            post=post,
            author=request.user,
            defaults={"score": form.cleaned_data["score"], "body": form.cleaned_data["body"]},
        )
        messages.success(request, "نظر شما ثبت شد.")
    else:
        messages.error(request, "امتیاز را انتخاب کن یا یک نظر بنویس.")
    return redirect("blog_detail", pk=post.pk)


@login_required
@require_POST
def delete_blog_comment(request, pk):
    comment = get_object_or_404(PostComment.objects.select_related("post"), pk=pk)
    if request.user.id != comment.author_id and not request.user.is_staff:
        raise Http404
    post_pk = comment.post_id
    comment.delete()
    messages.success(request, "نظر حذف شد.")
    return redirect("blog_detail", pk=post_pk)


@staff_member_required(login_url="login")
def blog_write(request, pk=None):
    post = get_object_or_404(Post, pk=pk) if pk else None
    category_form = BlogCategoryForm()
    post_form = PostForm(instance=post)
    if request.method == "POST":
        kind = request.POST.get("form")
        if kind == "category":
            category_form = BlogCategoryForm(request.POST)
            if category_form.is_valid():
                category_form.save()
                messages.success(request, "دسته اضافه شد.")
                return redirect("blog_write")
        elif kind == "category_edit":
            category = get_object_or_404(BlogCategory, pk=request.POST.get("id"))
            category_form = BlogCategoryForm(request.POST, instance=category)
            if category_form.is_valid():
                category_form.save()
                messages.success(request, "نام دسته عوض شد.")
            else:
                messages.error(request, "این نام خالی یا تکراری است.")
            return redirect("blog_write")
        elif kind == "page_seo" and (request.POST.get("id") or "").strip() == PageSeo.Key.BLOG:
            title, description, error = clean_seo_pair(request.POST)
            if error:
                messages.error(request, error)
            else:
                row, _created = PageSeo.objects.get_or_create(key=PageSeo.Key.BLOG)
                row.seo_title = title
                row.seo_description = description
                row.save(update_fields=["seo_title", "seo_description"])
                messages.success(request, "سئوی صفحه اصلی بلاگ ذخیره شد.")
            return redirect("blog_edit", pk=post.pk) if post else redirect("blog_write")
        elif kind == "blog_category_seo":
            category = get_object_or_404(BlogCategory, pk=request.POST.get("id"))
            title, description, error = clean_seo_pair(request.POST)
            if error:
                messages.error(request, error)
            else:
                category.seo_title = title
                category.seo_description = description
                category.save(update_fields=["seo_title", "seo_description"])
                messages.success(request, "سئوی این دسته بلاگ ذخیره شد.")
            return redirect("blog_write")
        elif kind == "category_delete":
            category = get_object_or_404(BlogCategory, pk=request.POST.get("id"))
            if category.posts.exists():
                messages.error(request, "این دسته نوشته دارد. اول نوشته‌ها را حذف کن یا به دسته دیگر ببر.")
            else:
                category.delete()
                messages.success(request, "دسته حذف شد.")
            return redirect("blog_write")
        elif kind == "delete" and post is not None:
            post.delete()
            messages.success(request, "نوشته حذف شد.")
            return redirect("blog_write")
        elif kind == "post":
            post_form = PostForm(request.POST, request.FILES, instance=post)
            if post_form.is_valid():
                saved = post_form.save(commit=False)
                if saved.author_id is None:
                    saved.author = request.user
                saved.save()
                messages.success(request, "نوشته ذخیره شد.")
                return redirect("blog_detail", pk=saved.pk)
    categories = list(BlogCategory.objects.annotate(post_count=Count("posts")))
    for category in categories:
        attach_audit(category, name=category.name)
    posts = list(Post.objects.select_related("category"))
    for item in posts:
        attach_audit(
            item,
            name=item.title,
            indexed=item.is_published,
            blocked="این نوشته پیش‌نویس است و در گوگل نمی‌آید.",
            has_image=bool(item.cover) or "<img" in (item.body or ""),
        )
    if post is not None:
        attach_audit(
            post,
            name=post.title,
            indexed=post.is_published,
            blocked="این نوشته پیش‌نویس است و در گوگل نمی‌آید.",
            has_image=bool(post.cover) or "<img" in (post.body or ""),
        )
    return render(
        request,
        "talent/blog_write.html",
        {
            "post": post,
            "category_form": category_form,
            "post_form": post_form,
            "categories": categories,
            "posts": posts,
            "blog_page": next(row for row in page_seo_rows() if row.key == PageSeo.Key.BLOG),
        },
    )


def _settlement_cards(profile):
    cards = []
    for item in profile.settlements.all()[:20]:
        item.when = jalali_label(timezone.localtime(item.created_at).date())
        cards.append(item)
    return cards


def _save_visit_file(request, visitor):
    recruit_id = request.POST.get("id")
    recruit = visitor.recruits.filter(pk=recruit_id).first() if str(recruit_id).isdigit() else None
    if recruit is None:
        messages.error(request, "این پذیرش پیدا نشد.")
        return
    try:
        stored = store_visit_file(request.FILES.get("file"))
    except FormError as error:
        messages.error(request, error.messages[0])
        return
    if recruit.visit_file:
        recruit.visit_file.delete(save=False)
    recruit.visit_file = stored
    recruit.save(update_fields=["visit_file"])
    messages.success(request, "فایل ثبت شد.")


@login_required(login_url="login")
def visit_file(request, pk):
    recruit = get_object_or_404(Profile.objects.select_related("recruited_by"), pk=pk)
    owner = recruit.recruited_by
    allowed = request.user.is_staff or (owner is not None and owner.user_id == request.user.id)
    if not allowed or not recruit.visit_file:
        raise Http404
    content_type = mimetypes.guess_type(recruit.visit_file.name)[0] or "application/octet-stream"
    response = FileResponse(recruit.visit_file.open("rb"), content_type=content_type)
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


def _visitors_url(name, city):
    params = {}
    if name:
        params["name"] = name
    if city:
        params["city"] = city
    url = reverse("visitors")
    if params:
        return f"{url}?{urlencode(params)}"
    return url


def _visitor_rows(name="", city=""):
    rows = (
        Profile.objects.filter(is_visitor=True)
        .select_related("user")
        .prefetch_related(
            Prefetch("recruits", queryset=Profile.objects.order_by("-created_at")),
            Prefetch("settlements", queryset=VisitorSettlement.objects.order_by("-created_at")),
        )
        .annotate(
            recruit_total=Count("recruits"),
            recruit_pending=Count("recruits", filter=Q(recruits__account_status="pending")),
            recruit_approved=Count("recruits", filter=Q(recruits__account_status="approved")),
            recruit_rejected=Count("recruits", filter=Q(recruits__account_status="rejected")),
            recruit_unsettled=Count(
                "recruits",
                filter=Q(recruits__account_status="approved", recruits__settlement__isnull=True),
            ),
        )
        .order_by("city", "display_name", "id")
    )
    if name:
        rows = rows.filter(display_name__icontains=name)
    if city:
        rows = rows.filter(city=city)
    return rows


def _specialty_status(profile):
    rank = {
        ProfileRole.Status.APPROVED: 3,
        ProfileRole.Status.PENDING: 2,
        ProfileRole.Status.REJECTED: 1,
    }
    status = {}
    for link in profile.role_links.select_related("role"):
        current = status.get(link.role.category_id)
        if current is None or rank[link.status] > rank[current]:
            status[link.role.category_id] = link.status
    return status


def _specialty_tree(checked_ids, status_by_category=None):
    status_by_category = status_by_category or {}
    chosen = {int(item) for item in checked_ids if str(item).isdigit() or isinstance(item, int)}
    children = {}
    for category in Category.objects.order_by("order", "name"):
        children.setdefault(category.parent_id, []).append(category)

    def build(parent_id):
        nodes = []
        for category in children.get(parent_id, []):
            nodes.append(
                {
                    "category": category,
                    "checked": category.id in chosen,
                    "status": status_by_category.get(category.id, ""),
                    "children": build(category.id),
                }
            )
        return nodes

    return build(None)


def _mirror_role(category):
    role = Role.objects.filter(category=category, name=category.name).order_by("id").first()
    if role is not None:
        return role
    slug = f"cat-{category.pk}"
    role = Role.objects.filter(slug=slug).first()
    if role is None:
        return Role.objects.create(category=category, name=category.name, slug=slug)
    role.name = category.name
    role.category = category
    role.save(update_fields=["name", "category"])
    return role


def _save_profile_specialties(profile, category_ids):
    valid_ids = set(Category.objects.filter(pk__in=category_ids).values_list("pk", flat=True))
    by_category = {}
    for link in profile.role_links.select_related("role"):
        by_category.setdefault(link.role.category_id, []).append(link)
    for category_id in valid_ids:
        rows = by_category.get(category_id) or []
        if rows:
            for link in rows:
                if link.status == ProfileRole.Status.REJECTED:
                    link.status = ProfileRole.Status.PENDING
                    link.save(update_fields=["status"])
        else:
            ProfileRole.objects.create(
                profile=profile,
                role=_mirror_role(Category.objects.get(pk=category_id)),
                status=ProfileRole.Status.PENDING,
            )
    for category_id, rows in by_category.items():
        if category_id not in valid_ids:
            for link in rows:
                link.delete()


def _write_recruit(profile, cleaned, role_ids):
    phone = cleaned["phone"]
    if phone_taken(phone):
        raise IntegrityError("phone taken")
    user = User(username=phone)
    user.set_unusable_password()
    user.save()
    recruit = profile_for(user)
    recruit.display_name = cleaned["display_name"]
    recruit.business_name = cleaned["business_name"]
    recruit.province = cleaned["province"]
    recruit.city = cleaned["city"]
    recruit.address = cleaned["address"]
    recruit.headline = cleaned["headline"]
    recruit.bio = cleaned["bio"]
    recruit.about_business = cleaned["about_business"]
    recruit.phone = phone
    recruit.contact_phone = cleaned.get("contact_phone") or ""
    recruit.instagram = cleaned["instagram"]
    recruit.telegram = cleaned["telegram"]
    recruit.whatsapp = cleaned["whatsapp"]
    recruit.website = cleaned["website"]
    recruit.latitude = cleaned["latitude"]
    recruit.longitude = cleaned["longitude"]
    recruit.account_status = "pending"
    recruit.recruited_by = profile
    if cleaned.get("avatar"):
        recruit.avatar = cleaned["avatar"]
    username = cleaned.get("username") or phone
    if user.username != username:
        user.username = username
        user.save(update_fields=["username"])
    recruit.save()
    ProfileRole.objects.bulk_create(
        [
            ProfileRole(profile=recruit, role_id=role_id, status=ProfileRole.Status.PENDING)
            for role_id in role_ids
        ]
    )
    return recruit


@staff_member_required(login_url="login")
def visitors(request):
    if not request.user.is_superuser:
        messages.error(request, "ویزیتورها را فقط مدیر می‌سازد.")
        return redirect("desk")
    name_query = (request.POST.get("filter_name") or request.GET.get("name") or "").strip()[:80]
    city_query = (request.POST.get("filter_city") or request.GET.get("city") or "").strip()[:80]
    form = VisitorAccountForm()
    if request.method == "POST":
        kind = request.POST.get("kind")
        item_id = request.POST.get("id")
        if kind == "create-visitor":
            form = VisitorAccountForm(request.POST)
            if form.is_valid():
                phone = form.cleaned_data["phone"]
                try:
                    with transaction.atomic():
                        user = User(username=phone)
                        user.set_unusable_password()
                        user.save()
                        profile = profile_for(user)
                        profile.phone = phone
                        profile.display_name = form.cleaned_data["display_name"]
                        profile.city = form.cleaned_data["city"]
                        profile.province = CITY_OF.get(profile.city, "")
                        profile.bio = form.cleaned_data["about"]
                        profile.account_status = "approved"
                        profile.accepted_terms_at = timezone.now()
                        profile.is_visitor = True
                        profile.save()
                except IntegrityError:
                    form.add_error("phone", "این شماره قبلاً ثبت شده.")
                else:
                    messages.success(
                        request,
                        "ویزیتور ساخته شد. با همین شماره و کد پیامکی وارد بخش پذیرش می‌شود.",
                    )
                    return redirect(_visitors_url(name_query, city_query))
        elif kind == "save-specs" and str(item_id).isdigit():
            profile = Profile.objects.filter(pk=int(item_id), is_visitor=True).select_related("user").first()
            if profile is None:
                messages.error(request, "این ویزیتور پیدا نشد.")
                return redirect(_visitors_url(name_query, city_query))
            edit = VisitorAccountForm(request.POST, user=profile.user)
            if not edit.is_valid():
                messages.error(request, "ویرایش ذخیره نشد. نام، شماره و شهر را درست وارد کن.")
                return redirect(_visitors_url(name_query, city_query))
            phone = edit.cleaned_data["phone"]
            profile.display_name = edit.cleaned_data["display_name"]
            profile.phone = phone
            profile.city = edit.cleaned_data["city"]
            profile.province = CITY_OF.get(profile.city, "")
            profile.bio = edit.cleaned_data["about"]
            profile.save()
            account = profile.user
            if account.username != phone:
                account.username = phone
                account.save(update_fields=["username"])
            messages.success(request, "مشخصات ویزیتور ذخیره شد.")
            return redirect(_visitors_url(name_query, city_query))
        elif kind == "close-visitor" and str(item_id).isdigit():
            profile = Profile.objects.filter(pk=int(item_id), is_visitor=True).first()
            if profile is None:
                messages.error(request, "این ویزیتور پیدا نشد.")
            else:
                profile.is_visitor = False
                profile.save(update_fields=["is_visitor"])
                messages.success(request, "ویزیتور غیرفعال شد. دیگر نمی‌تواند پذیرش کند. آمار قبلی‌اش می‌ماند.")
            return redirect(_visitors_url(name_query, city_query))
        elif kind == "settle" and str(item_id).isdigit():
            profile = Profile.objects.filter(pk=int(item_id), is_visitor=True).first()
            if profile is None:
                messages.error(request, "این ویزیتور پیدا نشد.")
                return redirect(_visitors_url(name_query, city_query))
            waiting = list(
                profile.recruits.filter(account_status="approved", settlement__isnull=True)
            )
            if not waiting:
                messages.error(request, "پذیرش تاییدشدهٔ تسویه‌نشده‌ای برای این ویزیتور نیست.")
                return redirect(_visitors_url(name_query, city_query))
            settlement = VisitorSettlement.objects.create(
                visitor=profile,
                amount=(request.POST.get("amount") or "").strip()[:40],
                note=(request.POST.get("note") or "").strip(),
                recruit_count=len(waiting),
            )
            Profile.objects.filter(pk__in=[item.pk for item in waiting]).update(settlement=settlement)
            messages.success(request, "تسویه ثبت شد و در کارتابل ویزیتور دیده می‌شود.")
            return redirect(_visitors_url(name_query, city_query))
    rows = []
    matched = _visitor_rows(name_query, city_query)
    for profile in matched:
        profile.recruit_rows = list(profile.recruits.all())[:8]
        profile.settlement_rows = []
        for item in list(profile.settlements.all())[:3]:
            item.when = jalali_label(timezone.localtime(item.created_at).date())
            profile.settlement_rows.append(item)
        rows.append(profile)
    return render(
        request,
        "talent/visitors.html",
        {
            "form": form,
            "visitors": rows,
            "name_query": name_query,
            "city_query": city_query,
            "city_options": city_choices(),
            "visitor_total": Profile.objects.filter(is_visitor=True).count(),
        },
    )


@login_required(login_url="login")
def field_desk(request):
    profile = profile_for(request.user)
    if not profile.is_visitor:
        raise Http404
    if request.method == "POST" and request.POST.get("kind") == "visit-file":
        _save_visit_file(request, profile)
        return redirect("field_desk")
    selected = [item for item in request.POST.getlist("categories") if str(item).isdigit()] if request.method == "POST" else []
    form = VisitorRecruitForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        categories = list(Category.objects.filter(pk__in=selected))
        if not categories:
            form.add_error(None, "حداقل یک تخصص را انتخاب کن.")
        else:
            try:
                with transaction.atomic():
                    _write_recruit(profile, form.cleaned_data, [_mirror_role(item).id for item in categories])
            except IntegrityError:
                form.add_error("phone", "این شماره قبلاً ثبت شده. شماره تکراری یا حساب موجود پذیرفته نمی‌شود.")
            else:
                messages.success(request, "کاربر ثبت شد و تا تایید مدیر در جستجو دیده نمی‌شود.")
                return redirect("field_desk")
    recruit_list = list(profile.recruits.order_by("-created_at"))
    counts = {
        "total": len(recruit_list),
        "pending": sum(item.account_status == "pending" for item in recruit_list),
        "approved": sum(item.account_status == "approved" for item in recruit_list),
        "rejected": sum(item.account_status == "rejected" for item in recruit_list),
    }
    buckets = {}
    for person in recruit_list:
        buckets.setdefault(timezone.localtime(person.created_at).date(), []).append(person)
    daily = [
        {
            "day": day,
            "label": jalali_label(day),
            "count": len(buckets[day]),
            "people": buckets[day],
        }
        for day in sorted(buckets, reverse=True)[:14]
    ]
    today_count = len(buckets.get(timezone.localdate(), []))
    return render(
        request,
        "talent/field.html",
        {
            "form": form,
            "specialty_tree": _specialty_tree(selected),
            "recruits": recruit_list[:50],
            "counts": counts,
            "daily": daily,
            "today_count": today_count,
            "settlements": _settlement_cards(profile),
        },
    )
