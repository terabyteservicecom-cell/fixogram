import json
import re
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import strip_tags

from talent.billing import public_profiles
from talent.html_text import sanitize_html
from talent.models import BlogCategory, Category, PageSeo, Post, ProfileRole

SITE_NAME = "فیکسوگرام"
DEFAULT_DESCRIPTION = (
    "فیکسوگرام جای پیدا کردن متخصص تعمیر لپ‌تاپ، کامپیوتر، مانیتور، "
    "آل‌این‌وان و آموزش تعمیر است."
)
PRIVATE_PREFIXES = (
    "/admin",
    "/me",
    "/desk",
    "/field",
    "/moderation",
    "/login",
    "/signup",
    "/messages",
    "/wallet",
    "/tickets",
    "/reports",
    "/banners",
    "/categories",
    "/broadcast",
    "/support",
    "/account",
    "/identity",
    "/blog/write",
)


def clip(text, limit=160):
    clean = re.sub(r"\s+", " ", strip_tags(text or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


_PHONE_IN_TEXT = re.compile(r"(?:\+98|0)?9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}")


def profile_audit(profile):
    errors = []
    notes = []
    score = 100
    roles = [
        link.role.name
        for link in profile.role_links.all()
        if link.status == ProfileRole.Status.APPROVED and link.role.name
    ]
    title = (profile.seo_title or "").strip()
    description = (profile.seo_description or "").strip()
    name = (profile.display_name or "").strip()
    city = (profile.city or "").strip()

    if profile.archived_at:
        errors.append("حساب بایگانی است و در گوگل نمی‌آید.")
        score -= 25
    if not profile.user.is_active:
        errors.append("حساب غیرفعال است و در گوگل نمی‌آید.")
        score -= 25
    if profile.account_status == "pending":
        errors.append("ثبت‌نام هنوز تایید نشده و صفحه در گوگل نمی‌آید.")
        score -= 25
    elif profile.account_status == "rejected":
        errors.append("ثبت‌نام رد شده و صفحه در گوگل نمی‌آید.")
        score -= 25
    if not roles:
        errors.append("هیچ تخصص تاییدشده‌ای نیست. بدون تخصص، گوگل این صفحه را نمی‌آورد.")
        score -= 20
    if not name:
        errors.append("نام نمایشی خالی است.")
        score -= 15

    if not title:
        notes.append("عنوان اختصاصی خالی است. سایت از نام یک عنوان خودکار می‌سازد.")
        score -= 12
    else:
        if len(title) < 35:
            notes.append(f"عنوان {len(title)} حرف است. بهتر است حدود ۵۰ تا ۶۰ حرف باشد.")
            score -= 8
        elif len(title) > 60:
            notes.append(f"عنوان {len(title)} حرف است. گوگل معمولاً بعد از ۶۰ حرف را نشان نمی‌دهد.")
            score -= 6
        if name and name not in title:
            notes.append("نام کاربر داخل عنوان نیست.")
            score -= 8
        if city and city not in title:
            notes.append("شهر داخل عنوان نیست.")
            score -= 6
        if roles and not any(role in title for role in roles):
            notes.append("تخصص تاییدشده داخل عنوان نیست.")
            score -= 6

    if not description:
        notes.append("توضیح اختصاصی خالی است. سایت از معرفی، تخصص و شهر یک توضیح می‌سازد.")
        score -= 12
    else:
        if len(description) < 80:
            notes.append(f"توضیح {len(description)} حرف است. بهتر است حدود ۱۲۰ تا ۱۶۰ حرف باشد.")
            score -= 10
        elif len(description) < 120:
            notes.append(f"توضیح {len(description)} حرف است. کمی کوتاه است؛ حدود ۱۲۰ تا ۱۶۰ حرف بهتر است.")
            score -= 5
        elif len(description) > 160:
            notes.append(f"توضیح {len(description)} حرف است. گوگل معمولاً بعد از ۱۶۰ حرف را قطع می‌کند.")
            score -= 5
        if city and city not in description:
            notes.append("شهر داخل توضیح نیست.")
            score -= 5

    if _PHONE_IN_TEXT.search(f"{title} {description}"):
        errors.append("شماره تلفن داخل عنوان یا توضیح است. آن را بردار.")
        score -= 20
    if not profile.avatar:
        notes.append("عکس چهره نیست. گوگل و شبکه‌ها عکس را کنار نتیجه نشان می‌دهند.")
        score -= 8
    if not city:
        notes.append("شهر ثبت نشده. برای جستجوی محلی لازم است.")
        score -= 8
    if not (profile.headline or "").strip():
        notes.append("یک خط معرفی خالی است.")
        score -= 5
    if not (profile.address or "").strip():
        notes.append("آدرس خالی است. برای کسب‌وکار محلی بهتر است پر شود.")
        score -= 4

    return {"score": max(0, min(100, score)), "errors": errors, "notes": notes}


def choose_seo(title, description, source):
    if source is None:
        return title, description
    custom_title = (getattr(source, "seo_title", "") or "").strip()
    custom_description = (getattr(source, "seo_description", "") or "").strip()
    return custom_title or title, custom_description or description


def clean_seo_pair(data):
    title = " ".join((data.get("seo_title") or "").split())
    description = " ".join((data.get("seo_description") or "").split())
    if len(title) > 70:
        return "", "", "عنوان گوگل حداکثر ۷۰ حرف است. حدود ۵۰ تا ۶۰ حرف بنویس."
    if len(description) > 170:
        return "", "", "توضیح گوگل حداکثر ۱۷۰ حرف است. حدود ۱۲۰ تا ۱۶۰ حرف بنویس."
    return title, description, ""


def page_audit(title, description, *, name="", indexed=True, blocked="", has_image=True):
    errors = []
    notes = []
    score = 100
    title = (title or "").strip()
    description = (description or "").strip()
    name = (name or "").strip()
    if not indexed:
        errors.append(blocked or "این صفحه در گوگل نمی‌آید.")
        score -= 30
    if not title:
        notes.append("عنوان اختصاصی خالی است. سایت یک عنوان خودکار می‌سازد.")
        score -= 12
    else:
        if len(title) < 35:
            notes.append(f"عنوان {len(title)} حرف است. بهتر است حدود ۵۰ تا ۶۰ حرف باشد.")
            score -= 8
        elif len(title) > 60:
            notes.append(f"عنوان {len(title)} حرف است. گوگل معمولاً بعد از ۶۰ حرف را نشان نمی‌دهد.")
            score -= 6
        if name and name not in title:
            notes.append("نام این بخش داخل عنوان نیست.")
            score -= 8
    if not description:
        notes.append("توضیح اختصاصی خالی است. سایت یک توضیح خودکار می‌سازد.")
        score -= 12
    else:
        if len(description) < 80:
            notes.append(f"توضیح {len(description)} حرف است. بهتر است حدود ۱۲۰ تا ۱۶۰ حرف باشد.")
            score -= 10
        elif len(description) < 120:
            notes.append(f"توضیح {len(description)} حرف است. کمی کوتاه است؛ حدود ۱۲۰ تا ۱۶۰ حرف بهتر است.")
            score -= 5
        elif len(description) > 160:
            notes.append(f"توضیح {len(description)} حرف است. گوگل معمولاً بعد از ۱۶۰ حرف را قطع می‌کند.")
            score -= 5
    if _PHONE_IN_TEXT.search(f"{title} {description}"):
        errors.append("شماره تلفن داخل عنوان یا توضیح است. آن را بردار.")
        score -= 20
    if not has_image:
        notes.append("عکسی در این صفحه نیست. گوگل نتیجه را بدون تصویر نشان می‌دهد.")
        score -= 8
    return {"score": max(0, min(100, score)), "errors": errors, "notes": notes}


PAGE_SEO = {
    PageSeo.Key.HOME: {
        "label": "صفحه اول",
        "name": "فیکسوگرام",
        "sample_title": "فیکسوگرام | متخصص تعمیر لپ‌تاپ و آموزش",
        "sample_text": "متخصص تاییدشده تعمیر لپ‌تاپ، کامپیوتر و آموزش را با شهر و امتیاز در فیکسوگرام پیدا کن.",
    },
    PageSeo.Key.JOBS: {
        "label": "استخدام و کاریابی",
        "name": "استخدام",
        "sample_title": "استخدام تعمیرکار لپ‌تاپ | فیکسوگرام",
        "sample_text": "آگهی استخدام و نیاز به کار تعمیر لپ‌تاپ، کامپیوتر و ماشین اداری را در فیکسوگرام ببین.",
    },
    PageSeo.Key.BLOG: {
        "label": "صفحه اصلی بلاگ",
        "name": "بلاگ",
        "sample_title": "بلاگ فیکسوگرام | آموزش و خبر تعمیر",
        "sample_text": "نوشته‌های آموزش و خبر تعمیر لپ‌تاپ، کامپیوتر و مانیتور را در بلاگ فیکسوگرام بخوان.",
    },
    PageSeo.Key.TERMS: {
        "label": "شرایط استفاده",
        "name": "شرایط",
        "sample_title": "شرایط استفاده از فیکسوگرام",
        "sample_text": "شرایط استفاده از فیکسوگرام برای متخصص‌ها و کسانی که دنبال تعمیر یا آموزش هستند.",
    },
}


def page_seo_rows():
    stored = {row.key: row for row in PageSeo.objects.all()}
    rows = []
    for key, meta in PAGE_SEO.items():
        row = stored.get(key) or PageSeo(key=key)
        attach_audit(row, name=meta["name"])
        row.seo_label = meta["label"]
        row.sample_title = meta["sample_title"]
        row.sample_text = meta["sample_text"]
        rows.append(row)
    return rows


def attach_audit(obj, *, name, indexed=True, blocked="", has_image=True):
    audit = page_audit(
        getattr(obj, "seo_title", ""),
        getattr(obj, "seo_description", ""),
        name=name,
        indexed=indexed,
        blocked=blocked,
        has_image=has_image,
    )
    obj.seo_score = audit["score"]
    obj.seo_errors = audit["errors"]
    obj.seo_notes = audit["notes"]
    return obj


def pack(request, title, description, *, path=None, image="", index=True, kind="website", json_ld=None):
    payload = ""
    if json_ld:
        payload = json.dumps(json_ld, ensure_ascii=False).replace("<", "\\u003c")
    return {
        "title": title,
        "description": clip(description),
        "canonical": request.build_absolute_uri(path if path is not None else request.path),
        "image": image,
        "robots": "index,follow" if index else "noindex,follow",
        "type": kind,
        "json": payload,
    }


def defaults(request):
    private = request.path.startswith(PRIVATE_PREFIXES)
    return pack(
        request,
        title="",
        description=DEFAULT_DESCRIPTION,
        index=not private,
    )


def _origin(request):
    return f"{request.scheme}://{request.get_host()}"


def home_page(request):
    origin = _origin(request)
    title, description = choose_seo(
        "فیکسوگرام — متخصص تعمیر و آموزش",
        DEFAULT_DESCRIPTION,
        PageSeo.objects.filter(key=PageSeo.Key.HOME).first(),
    )
    return pack(
        request,
        title=title,
        description=description,
        path="/",
        index=not request.GET,
        json_ld={
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": SITE_NAME,
            "url": origin + "/",
            "inLanguage": "fa",
            "potentialAction": {
                "@type": "SearchAction",
                "target": origin + "/?q={search_term_string}",
                "query-input": "required name=search_term_string",
            },
        },
    )


def section_page(request, category):
    parent = category.parent.name if category.parent_id else ""
    description = f"متخصص‌های تاییدشده {category.name} در فیکسوگرام، با شهر، امتیاز و نمونه کار."
    if parent:
        description = f"{category.name} زیرمجموعه {parent} است. {description}"
    title = f"{category.name} — فیکسوگرام"
    title, description = choose_seo(title, description, category)
    crumbs = [
        {"@type": "ListItem", "position": 1, "name": SITE_NAME, "item": _origin(request) + "/"},
    ]
    if category.parent_id:
        crumbs.append(
            {
                "@type": "ListItem",
                "position": 2,
                "name": parent,
                "item": request.build_absolute_uri(reverse("section", args=[category.parent.slug])),
            }
        )
    crumbs.append(
        {
            "@type": "ListItem",
            "position": len(crumbs) + 1,
            "name": category.name,
            "item": request.build_absolute_uri(request.path),
        }
    )
    return pack(
        request,
        title=title,
        description=description,
        path=request.path,
        index=not request.GET,
        json_ld={
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": category.name,
            "description": clip(description),
            "url": request.build_absolute_uri(request.path),
            "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": _origin(request) + "/"},
            "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": crumbs},
        },
    )


def profile_page(request, profile):
    roles = [
        link.role.name
        for link in profile.role_links.all()
        if link.status == ProfileRole.Status.APPROVED
    ]
    place = " ".join(part for part in (profile.city, profile.province) if part)
    bits = [profile.display_name]
    if profile.headline:
        bits.append(profile.headline)
    if roles:
        bits.append("متخصص " + "، ".join(roles[:4]))
    if place:
        bits.append(place)
    description = " — ".join(bits) + ". صفحه متخصص در فیکسوگرام."
    custom_title = (profile.seo_title or "").strip()
    custom_description = (profile.seo_description or "").strip()
    title = custom_title or f"{profile.display_name} — فیکسوگرام"
    if custom_description:
        description = custom_description
    image = request.build_absolute_uri(profile.avatar.url) if profile.avatar else ""
    url = request.build_absolute_uri(reverse("profile", args=[profile.pk]))
    data = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": profile.display_name,
        "description": clip(description),
        "url": url,
    }
    if image:
        data["image"] = image
    if profile.address or profile.city or profile.province:
        address = {"@type": "PostalAddress", "addressCountry": "IR"}
        if profile.address:
            address["streetAddress"] = profile.address
        if profile.city:
            address["addressLocality"] = profile.city
        if profile.province:
            address["addressRegion"] = profile.province
        data["address"] = address
    if roles:
        data["knowsAbout"] = roles[:8]
    return pack(
        request,
        title=title,
        description=description,
        path=reverse("profile", args=[profile.pk]),
        image=image,
        index=profile.is_public(),
        kind="profile",
        json_ld=data,
    )


def blog_index(request, category=None):
    if category:
        title = f"{category.name} — بلاگ فیکسوگرام"
        description = f"نوشته‌های دسته {category.name} در بلاگ فیکسوگرام."
        path = reverse("blog") + f"?category={category.pk}"
        title, description = choose_seo(title, description, category)
    else:
        title = "بلاگ — فیکسوگرام"
        description = "نوشته‌های فیکسوگرام درباره تعمیر لپ‌تاپ، کامپیوتر، مانیتور و آموزش."
        path = reverse("blog")
        title, description = choose_seo(
            title,
            description,
            PageSeo.objects.filter(key=PageSeo.Key.BLOG).first(),
        )
    paging = request.GET.get("page", "").strip() not in ("", "1")
    return pack(
        request,
        title=title,
        description=description,
        path=path,
        index=not paging,
        json_ld={
            "@context": "https://schema.org",
            "@type": "Blog",
            "name": title,
            "description": clip(description),
            "url": request.build_absolute_uri(path),
            "inLanguage": "fa",
        },
    )


def blog_post(request, post):
    author = ""
    if post.author_id and hasattr(post.author, "profile"):
        author = post.author.profile.display_name
    description = clip(sanitize_html(post.body)) or post.title
    title = f"{post.title} — بلاگ فیکسوگرام"
    title, description = choose_seo(title, description, post)
    url = request.build_absolute_uri(reverse("blog_detail", args=[post.pk]))
    data = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.title,
        "description": description,
        "datePublished": post.created_at.isoformat(),
        "dateModified": post.updated_at.isoformat(),
        "articleSection": post.category.name,
        "inLanguage": "fa",
        "mainEntityOfPage": url,
        "publisher": {"@type": "Organization", "name": SITE_NAME},
    }
    if author:
        data["author"] = {"@type": "Person", "name": author}
    return pack(
        request,
        title=title,
        description=description,
        path=reverse("blog_detail", args=[post.pk]),
        index=post.is_published,
        kind="article",
        json_ld=data,
    )


def jobs_page(request):
    title, description = choose_seo(
        "استخدام و نیاز به کار — فیکسوگرام",
        "آگهی استخدام و نیاز به کار تعمیر لپ‌تاپ، کامپیوتر و ماشین اداری در فیکسوگرام.",
        PageSeo.objects.filter(key=PageSeo.Key.JOBS).first(),
    )
    return pack(
        request,
        title=title,
        description=description,
        path="/jobs/",
        index=not request.GET,
    )


def terms_page(request):
    title, description = choose_seo(
        "شرایط استفاده — فیکسوگرام",
        "شرایط استفاده از فیکسوگرام برای متخصص‌ها و کسانی که دنبال تعمیر یا آموزش هستند.",
        PageSeo.objects.filter(key=PageSeo.Key.TERMS).first(),
    )
    return pack(request, title=title, description=description, path="/terms/")


def robots_txt(request):
    lines = ["User-agent: *", "Allow: /"]
    for prefix in PRIVATE_PREFIXES:
        lines.append(f"Disallow: {prefix}/" if not prefix.endswith("/") else f"Disallow: {prefix}")
    lines.append(f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}")
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")


def sitemap_xml(request):
    rows = []

    def add(path):
        loc = escape(request.build_absolute_uri(path))
        rows.append(f"<url><loc>{loc}</loc></url>")

    add("/")
    add("/jobs/")
    add("/blog/")
    add("/terms/")
    for category in Category.objects.exclude(slug="").order_by("pk"):
        add(reverse("section", args=[category.slug]))
    for category in BlogCategory.objects.order_by("pk"):
        add(reverse("blog") + f"?category={category.pk}")
    for profile in public_profiles().order_by("pk").only("id"):
        add(reverse("profile", args=[profile.pk]))
    for post in Post.objects.filter(is_published=True).order_by("pk").only("id"):
        add(reverse("blog_detail", args=[post.pk]))
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(rows)
        + "</urlset>"
    )
    return HttpResponse(body, content_type="application/xml; charset=utf-8")
