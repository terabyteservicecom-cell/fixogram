from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import Avg
from django.utils import timezone

from talent.dates import jalali_label, persian_digits
from talent.private_storage import IdentityStorage


class Category(models.Model):
    name = models.CharField("نام دسته", max_length=80)
    slug = models.SlugField(unique=True, blank=True)
    parent = models.ForeignKey(
        "self",
        verbose_name="دسته مادر",
        related_name="children",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    order = models.PositiveSmallIntegerField("ترتیب", default=0)
    seo_title = models.CharField("عنوان گوگل", max_length=70, blank=True)
    seo_description = models.CharField("توضیح گوگل", max_length=170, blank=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "دسته"
        verbose_name_plural = "دسته‌ها"

    def __str__(self):
        names = [self.name]
        parent = self.parent if self.parent_id else None
        guard = 0
        while parent is not None and guard < 6:
            names.append(parent.name)
            parent = parent.parent if parent.parent_id else None
            guard += 1
        return " / ".join(reversed(names))

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"cat-{uuid4().hex[:10]}"
        super().save(*args, **kwargs)

    def descendant_ids(self):
        ids = [self.pk]
        for child in self.children.all():
            ids.extend(child.descendant_ids())
        return ids


class Role(models.Model):
    category = models.ForeignKey(
        Category,
        verbose_name="دسته",
        related_name="roles",
        on_delete=models.CASCADE,
    )
    name = models.CharField("عنوان", max_length=80)
    slug = models.SlugField(unique=True, blank=True)

    class Meta:
        ordering = ["category__order", "name"]
        verbose_name = "عنوان شغلی"
        verbose_name_plural = "عنوان‌های شغلی"

    def __str__(self):
        return f"{self.category.name} / {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"role-{uuid4().hex[:10]}"
        super().save(*args, **kwargs)


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        related_name="profile",
        on_delete=models.CASCADE,
    )
    display_name = models.CharField("نام نمایشی", max_length=80)
    city = models.CharField("شهر", max_length=80, blank=True)
    headline = models.CharField("یک خط معرفی", max_length=140, blank=True)
    bio = models.TextField("درباره", blank=True)
    phone = models.CharField("شماره", max_length=20, blank=True)
    contact_phone = models.CharField("شماره تماس نمایشی", max_length=20, blank=True)
    avatar = models.ImageField("عکس چهره", upload_to="avatars/", blank=True)
    listed_until = models.DateTimeField("نمایش تا", null=True, blank=True)
    welcome_seen_at = models.DateTimeField("دیدن پیام مدیر", null=True, blank=True)
    accepted_terms_at = models.DateTimeField("قبول شرایط", null=True, blank=True)
    archived_at = models.DateTimeField("بایگانی", null=True, blank=True)
    account_status = models.CharField(
        "وضعیت ثبت‌نام",
        max_length=20,
        choices=[
            ("pending", "در انتظار تایید"),
            ("approved", "تایید شده"),
            ("rejected", "رد شده"),
        ],
        default="approved",
    )
    rejection_note = models.TextField("دلیل رد", blank=True)
    seo_title = models.CharField("عنوان گوگل", max_length=70, blank=True)
    seo_description = models.CharField("توضیح گوگل", max_length=170, blank=True)
    is_support = models.BooleanField("پشتیبان", default=False)
    is_visitor = models.BooleanField("ویزیتور", default=False)
    recruited_by = models.ForeignKey(
        "self",
        verbose_name="ویزیتور پذیرنده",
        related_name="recruits",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    settlement = models.ForeignKey(
        "VisitorSettlement",
        verbose_name="تسویه",
        related_name="covered_recruits",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    visit_file = models.FileField(
        "فایل پذیرش",
        upload_to="visits/%Y/%m/",
        storage=IdentityStorage(),
        blank=True,
        max_length=240,
    )
    business_name = models.CharField("نام مجموعه", max_length=120, blank=True)
    about_business = models.TextField("معرفی مجموعه", blank=True)
    province = models.CharField("استان", max_length=80, blank=True)
    address = models.CharField("آدرس", max_length=240, blank=True)
    latitude = models.DecimalField(
        "عرض جغرافیایی", max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        "طول جغرافیایی", max_digits=9, decimal_places=6, null=True, blank=True
    )
    instagram = models.CharField("اینستاگرام", max_length=200, blank=True)
    telegram = models.CharField("تلگرام", max_length=200, blank=True)
    whatsapp = models.CharField("واتساپ", max_length=200, blank=True)
    website = models.CharField("وب‌سایت", max_length=200, blank=True)
    is_vip = models.BooleanField("VIP", default=False)
    staff_score = models.PositiveSmallIntegerField("امتیاز مدیریت", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "صفحه شخص"
        verbose_name_plural = "صفحه‌ها"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["phone"],
                condition=~models.Q(phone=""),
                name="unique_profile_phone",
            )
        ]

    def __str__(self):
        return self.display_name

    def approved_roles(self):
        return self.role_links.filter(status=ProfileRole.Status.APPROVED).select_related(
            "role", "role__category"
        )

    def score_summary(self):
        data = self.ratings.aggregate(avg=Avg("score"), count=models.Count("id"))
        return data["avg"] or 0, data["count"]

    def is_public(self):
        if self.archived_at or self.account_status != "approved" or not self.user.is_active:
            return False
        if self.user.is_staff:
            return False
        return self.role_links.filter(status=ProfileRole.Status.APPROVED).exists()

    def social_link(self, kind):
        raw = (getattr(self, kind, "") or "").strip()
        if not raw:
            return ""
        if raw.startswith(("http://", "https://")):
            return raw
        handle = raw.lstrip("@").strip().strip("/")
        if kind == "instagram":
            return "https://instagram.com/" + handle
        if kind == "telegram":
            return "https://t.me/" + handle.removeprefix("t.me/")
        if kind == "whatsapp":
            digits = "".join(ch for ch in handle if ch.isdigit())
            if len(digits) >= 8:
                if digits.startswith("0"):
                    digits = "98" + digits[1:]
                return "https://wa.me/" + digits
            return "https://wa.me/" + handle
        return "https://" + handle

    @property
    def instagram_url(self):
        return self.social_link("instagram")

    @property
    def telegram_url(self):
        return self.social_link("telegram")

    @property
    def whatsapp_url(self):
        return self.social_link("whatsapp")

    @property
    def website_url(self):
        return self.social_link("website")


class VisitorSettlement(models.Model):
    visitor = models.ForeignKey(
        Profile,
        verbose_name="ویزیتور",
        related_name="settlements",
        on_delete=models.CASCADE,
    )
    amount = models.CharField("مبلغ", max_length=40, blank=True)
    note = models.TextField("شرح", blank=True)
    recruit_count = models.PositiveIntegerField("تعداد تسویه‌شده", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "تسویه ویزیتور"
        verbose_name_plural = "تسویه‌های ویزیتور"

    def __str__(self):
        return f"{self.visitor} — {self.recruit_count}"


class ProfileRole(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار تایید"
        APPROVED = "approved", "تایید شده"
        REJECTED = "rejected", "رد شده"

    profile = models.ForeignKey(
        Profile,
        verbose_name="شخص",
        related_name="role_links",
        on_delete=models.CASCADE,
    )
    role = models.ForeignKey(Role, verbose_name="عنوان", on_delete=models.CASCADE)
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "role"], name="unique_profile_role")
        ]
        verbose_name = "نقش شخص"
        verbose_name_plural = "نقش‌های اشخاص"

    def __str__(self):
        return f"{self.profile} — {self.role.name} ({self.get_status_display()})"


class Photo(models.Model):
    profile = models.ForeignKey(Profile, related_name="photos", on_delete=models.CASCADE)
    image = models.ImageField("عکس", upload_to="photos/")
    caption = models.CharField("توضیح", max_length=140, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "عکس"
        verbose_name_plural = "عکس‌ها"

    def __str__(self):
        return self.caption or f"عکس {self.pk}"


class WorkSample(models.Model):
    profile = models.ForeignKey(Profile, related_name="works", on_delete=models.CASCADE)
    title = models.CharField("نام کار", max_length=140)
    year = models.CharField("سال", max_length=10, blank=True)
    description = models.TextField("توضیح", blank=True)
    image = models.ImageField("عکس", upload_to="works/", blank=True)
    link = models.URLField("لینک", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "نمونه‌کار"
        verbose_name_plural = "نمونه‌کارها"

    def __str__(self):
        return self.title


class ResumeItem(models.Model):
    profile = models.ForeignKey(Profile, related_name="resume_items", on_delete=models.CASCADE)
    title = models.CharField("نام پروژه", max_length=160)
    role_name = models.CharField("سمت شما", max_length=80, blank=True)
    year = models.CharField("سال", max_length=20, blank=True)
    description = models.TextField("توضیح", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "-created_at"]
        verbose_name = "سابقه"
        verbose_name_plural = "رزومه"

    def __str__(self):
        return self.title


class Thread(models.Model):
    user_low = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="threads_low",
        on_delete=models.CASCADE,
    )
    user_high = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="threads_high",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_low", "user_high"], name="unique_thread_pair"),
            models.CheckConstraint(
                condition=~models.Q(user_low=models.F("user_high")),
                name="thread_users_differ",
            ),
        ]
        verbose_name = "گفتگو"
        verbose_name_plural = "گفتگوها"

    def __str__(self):
        return f"گفتگو {self.pk}"

    @classmethod
    def between(cls, user, other):
        if user.id == other.id:
            raise ValueError("گفتگو با خود شخص ممکن نیست.")
        low, high = (user, other) if user.id < other.id else (other, user)
        thread, _ = cls.objects.get_or_create(user_low=low, user_high=high)
        return thread

    def involves(self, user):
        return user.id in (self.user_low_id, self.user_high_id)

    def counterpart(self, user):
        return self.user_high if self.user_low_id == user.id else self.user_low


class Message(models.Model):
    thread = models.ForeignKey(Thread, related_name="messages", on_delete=models.CASCADE)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField("متن")
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=[
            ("pending", "در انتظار تایید"),
            ("approved", "تایید شده"),
            ("rejected", "رد شده"),
        ],
        default="pending",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField("زمان بررسی", null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "پیام"
        verbose_name_plural = "پیام‌ها"

    def __str__(self):
        return self.body[:40]


class PhoneRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار تایید"
        APPROVED = "approved", "تایید شده"
        REJECTED = "rejected", "رد شده"

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="درخواست‌کننده",
        related_name="phone_requests",
        on_delete=models.CASCADE,
    )
    profile = models.ForeignKey(
        Profile,
        verbose_name="صاحب شماره",
        related_name="phone_requests",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField("زمان بررسی", null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["requester", "profile"],
                name="unique_phone_request",
            )
        ]
        ordering = ["-created_at"]
        verbose_name = "درخواست شماره"
        verbose_name_plural = "درخواست‌های شماره"

    def __str__(self):
        return f"{self.requester} → {self.profile}"


class Rating(models.Model):
    rater = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="امتیازدهنده",
        related_name="ratings_given",
        on_delete=models.CASCADE,
    )
    profile = models.ForeignKey(
        Profile,
        verbose_name="شخص",
        related_name="ratings",
        on_delete=models.CASCADE,
    )
    score = models.PositiveSmallIntegerField("امتیاز")
    comment = models.TextField("نظر", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["rater", "profile"], name="unique_rating")
        ]
        ordering = ["-created_at"]
        verbose_name = "امتیاز"
        verbose_name_plural = "امتیازها"

    def __str__(self):
        return f"{self.score} برای {self.profile}"


class IdentityDocument(models.Model):
    class Kind(models.TextChoices):
        NATIONAL_CARD = "national_card", "کارت ملی"
        BIRTH_CERTIFICATE = "birth_certificate", "شناسنامه"
        BUSINESS_LICENSE = "business_license", "جواز کسب"
        OTHER = "other", "مدرک دیگر"

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار تایید"
        APPROVED = "approved", "تایید شده"
        REJECTED = "rejected", "رد شده"

    profile = models.ForeignKey(
        Profile,
        verbose_name="شخص",
        related_name="identity_documents",
        on_delete=models.CASCADE,
    )
    kind = models.CharField("نوع", max_length=32, choices=Kind.choices)
    title = models.CharField("عنوان", max_length=80, blank=True)
    file = models.FileField(
        "فایل",
        upload_to="%Y/%m/",
        max_length=240,
        storage=IdentityStorage(),
    )
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField("زمان بررسی", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "مدرک هویت"
        verbose_name_plural = "مدارک هویت"

    def __str__(self):
        return self.title or self.get_kind_display()

    def label(self):
        if self.kind == self.Kind.OTHER and self.title:
            return self.title
        return self.get_kind_display()


class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        related_name="wallet",
        on_delete=models.CASCADE,
    )
    balance = models.PositiveIntegerField("موجودی تومان", default=0)

    class Meta:
        verbose_name = "کیف پول"
        verbose_name_plural = "کیف پول‌ها"

    def __str__(self):
        return f"{self.user} / {self.balance}"


class WalletEntry(models.Model):
    class Kind(models.TextChoices):
        CHARGE = "charge", "شارژ"
        PURCHASE = "purchase", "خرید سال"

    wallet = models.ForeignKey(
        Wallet,
        verbose_name="کیف پول",
        related_name="entries",
        on_delete=models.CASCADE,
    )
    amount = models.IntegerField("مبلغ")
    kind = models.CharField("نوع", max_length=20, choices=Kind.choices)
    note = models.CharField("شرح", max_length=140, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "گردش کیف پول"
        verbose_name_plural = "گردش کیف پول"

    def __str__(self):
        return f"{self.amount} {self.kind}"


class ChargeRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار تایید"
        APPROVED = "approved", "تایید شده"
        REJECTED = "rejected", "رد شده"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        related_name="charge_requests",
        on_delete=models.CASCADE,
    )
    amount = models.PositiveIntegerField("مبلغ تومان")
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField("زمان بررسی", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "درخواست شارژ"
        verbose_name_plural = "درخواست‌های شارژ"

    def __str__(self):
        return f"{self.user} / {self.amount}"


class BlogCategory(models.Model):
    name = models.CharField("نام دسته", max_length=80, unique=True)
    order = models.PositiveSmallIntegerField("ترتیب", default=0)
    seo_title = models.CharField("عنوان گوگل", max_length=70, blank=True)
    seo_description = models.CharField("توضیح گوگل", max_length=170, blank=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "دسته بلاگ"
        verbose_name_plural = "دسته‌های بلاگ"

    def __str__(self):
        return self.name


class Post(models.Model):
    title = models.CharField("عنوان", max_length=160)
    seo_title = models.CharField("عنوان گوگل", max_length=70, blank=True)
    seo_description = models.CharField("توضیح گوگل", max_length=170, blank=True)
    category = models.ForeignKey(
        BlogCategory,
        verbose_name="دسته",
        related_name="posts",
        on_delete=models.PROTECT,
    )
    body = models.TextField("متن")
    is_published = models.BooleanField("در بلاگ نشان داده شود", default=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="نویسنده",
        related_name="posts",
        null=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "نوشته"
        verbose_name_plural = "نوشته‌ها"

    def __str__(self):
        return self.title

    def comment_summary(self):
        data = self.comments.aggregate(
            avg=Avg("score"),
            scored=models.Count("id", filter=models.Q(score__isnull=False)),
            total=models.Count("id"),
        )
        return data["avg"] or 0, data["scored"] or 0, data["total"] or 0


class PageSeo(models.Model):
    class Key(models.TextChoices):
        HOME = "home", "صفحه اول"
        JOBS = "jobs", "استخدام و کاریابی"
        BLOG = "blog", "فهرست بلاگ"
        TERMS = "terms", "شرایط استفاده"

    key = models.CharField("صفحه", max_length=20, unique=True, choices=Key.choices)
    seo_title = models.CharField("عنوان گوگل", max_length=70, blank=True)
    seo_description = models.CharField("توضیح گوگل", max_length=170, blank=True)

    class Meta:
        verbose_name = "سئوی صفحه"
        verbose_name_plural = "سئوی صفحه‌ها"

    def __str__(self):
        return self.get_key_display()


class HomeCopy(models.Model):
    eyebrow = models.CharField("برچسب بالای عنوان", max_length=80, blank=True)
    headline = models.CharField("عنوان اصلی", max_length=200, blank=True)
    lead = models.TextField("توضیح زیر عنوان", blank=True)
    section_link = models.CharField("متن لینک بخش", max_length=80, blank=True)
    empty_people = models.CharField("وقتی متخصصی نیست", max_length=200, blank=True)
    jobs_title = models.CharField("عنوان استخدام", max_length=80, blank=True)
    jobs_lead = models.TextField("توضیح استخدام", blank=True)
    empty_jobs = models.CharField("وقتی آگهی نیست", max_length=200, blank=True)
    jobs_button = models.CharField("دکمه آگهی‌ها", max_length=80, blank=True)
    footer = models.TextField("متن پایین صفحه", blank=True)
    job_warning = models.TextField("زنگ خطر قبل از همکاری", blank=True)

    class Meta:
        verbose_name = "نوشته صفحه اصلی"
        verbose_name_plural = "نوشته‌های صفحه اصلی"

    def __str__(self):
        return "نوشته‌های صفحه اصلی"


class PostComment(models.Model):
    post = models.ForeignKey(
        Post,
        verbose_name="نوشته",
        related_name="comments",
        on_delete=models.CASCADE,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="نویسنده نظر",
        related_name="post_comments",
        on_delete=models.CASCADE,
    )
    score = models.PositiveSmallIntegerField("امتیاز", null=True, blank=True)
    body = models.TextField("نظر", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "author"], name="unique_post_comment")
        ]
        ordering = ["-created_at"]
        verbose_name = "نظر بلاگ"
        verbose_name_plural = "نظرهای بلاگ"

    def __str__(self):
        return f"{self.author} / {self.post}"


class Banner(models.Model):
    class Place(models.TextChoices):
        HOME = "home", "صفحه اول"
        SECTION = "section", "بخش تخصص"
        BLOG = "blog", "بلاگ"

    title = models.CharField("عنوان", max_length=80, blank=True)
    image = models.ImageField("عکس بنر", upload_to="banners/")
    link = models.URLField("لینک")
    place = models.CharField(
        "جای نمایش",
        max_length=20,
        choices=Place.choices,
        blank=True,
        default=Place.HOME,
    )
    category = models.ForeignKey(
        Category,
        verbose_name="بخش",
        related_name="banners",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    order = models.PositiveSmallIntegerField("ترتیب", default=0)
    is_active = models.BooleanField("نمایش داده شود", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "بنر"
        verbose_name_plural = "بنرها"

    def __str__(self):
        return self.title or self.link


class BannerClick(models.Model):
    banner = models.ForeignKey(
        Banner,
        verbose_name="بنر",
        related_name="clicks",
        on_delete=models.CASCADE,
    )
    clicked_at = models.DateTimeField("زمان کلیک", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-clicked_at"]
        verbose_name = "کلیک بنر"
        verbose_name_plural = "کلیک بنرها"

    def __str__(self):
        return f"{self.banner} — {self.clicked_at:%Y-%m-%d %H:%M}"


class PageView(models.Model):
    path = models.CharField("مسیر", max_length=200)
    viewed_at = models.DateTimeField("زمان بازدید", auto_now_add=True, db_index=True)
    session_key = models.CharField("نشست", max_length=40, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        related_name="page_views",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["-viewed_at"]
        verbose_name = "بازدید"
        verbose_name_plural = "بازدیدها"

    def __str__(self):
        return f"{self.path} — {self.viewed_at:%Y-%m-%d %H:%M}"


class Presence(models.Model):
    session_key = models.CharField("نشست", max_length=40, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        related_name="presences",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    path = models.CharField("صفحه", max_length=200, blank=True)
    last_seen = models.DateTimeField("آخرین فعالیت", db_index=True)

    class Meta:
        verbose_name = "حضور"
        verbose_name_plural = "حاضرها"

    def __str__(self):
        return self.session_key


class JobPost(models.Model):
    class Kind(models.TextChoices):
        HIRE = "hire", "استخدام"
        SEEK = "seek", "نیاز به کار"

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار تایید"
        APPROVED = "approved", "تایید شده"
        REJECTED = "rejected", "رد شده"

    class Duration(models.IntegerChoices):
        WEEK = 7, "۷ روز"
        HALF = 15, "۱۵ روز"
        MONTH = 30, "یک ماه"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="نویسنده",
        related_name="job_posts",
        on_delete=models.CASCADE,
    )
    kind = models.CharField("نوع", max_length=20, choices=Kind.choices)
    title = models.CharField("عنوان", max_length=140)
    category = models.ForeignKey(
        Category,
        verbose_name="زمینه",
        related_name="job_posts",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    city = models.CharField("شهر", max_length=80, blank=True)
    body = models.TextField("شرح")
    duration_days = models.PositiveSmallIntegerField(
        "مدت نمایش",
        choices=Duration.choices,
        default=Duration.WEEK,
        help_text="از لحظهٔ تایید مدیر روی سایت می‌ماند. بعد از این مدت آگهی خودکار حذف می‌شود.",
    )
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField("زمان بررسی", null=True, blank=True)
    expires_at = models.DateTimeField("حذف در", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "آگهی کار"
        verbose_name_plural = "آگهی‌های کار"

    def __str__(self):
        return self.title

    def days_left(self):
        if self.expires_at is None:
            return None
        seconds = (self.expires_at - timezone.now()).total_seconds()
        if seconds <= 0:
            return 0
        return (int(seconds) + 86399) // 86400

    def stay_line(self):
        if self.expires_at:
            when = jalali_label(timezone.localtime(self.expires_at).date())
            return f"{persian_digits(self.days_left())} روز مانده، تا {when}"
        return f"بعد از تایید، {self.get_duration_days_display()} روی سایت می‌ماند"

    @classmethod
    def purge_expired(cls):
        cls.objects.filter(expires_at__lte=timezone.now()).delete()

    @classmethod
    def visible(cls):
        cls.purge_expired()
        return cls.objects.filter(
            status=cls.Status.APPROVED,
            expires_at__gt=timezone.now(),
        )


class SmsSetting(models.Model):
    api_key = models.CharField("کلید API کاوه‌نگار", max_length=120, blank=True)
    template = models.CharField("نام قالب اعتبارسنجی", max_length=80, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیم پیامک"
        verbose_name_plural = "تنظیم پیامک"

    def __str__(self):
        return "کاوه‌نگار"

    @classmethod
    def current(cls):
        row, _ = cls.objects.get_or_create(pk=1)
        return row


class LoginCode(models.Model):
    phone = models.CharField("شماره", max_length=11, db_index=True)
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField("اعتبار تا")
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "کد ورود"
        verbose_name_plural = "کدهای ورود"

    def __str__(self):
        return self.phone


class WelcomeMessage(models.Model):
    body = models.TextField("متن", blank=True)
    audio = models.FileField("صدا", upload_to="welcome/", blank=True)
    video = models.FileField("ویدیو", upload_to="welcome/", blank=True)
    is_active = models.BooleanField("روشن", default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "پیام مدیر"
        verbose_name_plural = "پیام مدیر"

    def __str__(self):
        return "پیام خوش‌آمد"

    def is_ready(self):
        if not self.is_active:
            return False
        return bool(self.body.strip() or self.audio or self.video)


class GroupMessage(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="فرستنده",
        related_name="group_messages",
        on_delete=models.CASCADE,
    )
    category = models.ForeignKey(
        Category,
        verbose_name="دسته",
        related_name="group_messages",
        on_delete=models.CASCADE,
    )
    body = models.TextField("متن")
    recipient_count = models.PositiveIntegerField("تعداد گیرنده", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "پیام گروهی"
        verbose_name_plural = "پیام‌های گروهی"

    def __str__(self):
        return f"{self.category} — {self.body[:40]}"


class Ticket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "در انتظار"
        ANSWERED = "answered", "پاسخ داده شد"
        CLOSED = "closed", "بسته شد"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="فرستنده",
        related_name="tickets",
        on_delete=models.CASCADE,
    )
    subject = models.CharField("موضوع", max_length=120)
    body = models.TextField("متن")
    reply = models.TextField("پاسخ مدیریت", blank=True)
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    replied_at = models.DateTimeField("زمان پاسخ", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "تیکت"
        verbose_name_plural = "تیکت‌ها"

    def __str__(self):
        return self.subject


class ViolationReport(models.Model):
    class Reason(models.TextChoices):
        FAKE = "fake", "اطلاعات نادرست"
        ABUSE = "abuse", "رفتار توهین‌آمیز"
        SCAM = "scam", "کلاهبرداری"
        SPAM = "spam", "تبلیغ اسپم"
        OTHER = "other", "سایر"

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار"
        REVIEWED = "reviewed", "رسیدگی شد"
        DISMISSED = "dismissed", "رد شد"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="گزارش‌دهنده",
        related_name="violation_reports",
        on_delete=models.CASCADE,
    )
    profile = models.ForeignKey(
        Profile,
        verbose_name="کاربر گزارش‌شده",
        related_name="violation_reports",
        on_delete=models.CASCADE,
    )
    job = models.ForeignKey(
        "JobPost",
        verbose_name="آگهی",
        related_name="violation_reports",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    reason = models.CharField("نوع تخلف", max_length=20, choices=Reason.choices)
    body = models.TextField("شرح")
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField("زمان رسیدگی", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "گزارش تخلف"
        verbose_name_plural = "گزارش تخلف‌ها"

    def __str__(self):
        return f"{self.get_reason_display()} — {self.profile}"


class SupportAccess(models.Model):
    profile = models.OneToOneField(
        Profile,
        verbose_name="پشتیبان",
        related_name="access",
        on_delete=models.CASCADE,
    )
    moderate = models.BooleanField("صف تایید", default=False)
    categories = models.BooleanField("دسته‌ها", default=False)
    banners = models.BooleanField("بنرها", default=False)
    blog = models.BooleanField("بلاگ", default=False)
    broadcast = models.BooleanField("پیام گروهی", default=False)
    tickets = models.BooleanField("تیکت و تخلف", default=False)
    reports = models.BooleanField("گزارشات", default=False)

    class Meta:
        verbose_name = "دسترسی پشتیبان"
        verbose_name_plural = "دسترسی پشتیبان‌ها"

    def labels(self):
        from talent.access import PERMISSIONS

        return [label for code, label in PERMISSIONS if getattr(self, code)]


class StaffLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="پشتیبان",
        related_name="staff_logs",
        on_delete=models.CASCADE,
    )
    path = models.CharField("مسیر", max_length=200)
    summary = models.CharField("کار", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "لاگ پشتیبان"
        verbose_name_plural = "لاگ پشتیبان‌ها"

    def __str__(self):
        return self.summary


class PushSubscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        related_name="push_subscriptions",
        on_delete=models.CASCADE,
    )
    endpoint = models.TextField("نشانی")
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["endpoint"], name="unique_push_endpoint"),
        ]
        verbose_name = "اعلان گوشی"
        verbose_name_plural = "اعلان‌های گوشی"

    def __str__(self):
        return f"{self.user_id}"


class Bookmark(models.Model):
    class Kind(models.TextChoices):
        SECTION = "section", "بخش"
        PROFILE = "profile", "متخصص"
        JOB = "job", "آگهی"
        POST = "post", "نوشته"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        related_name="bookmarks",
        on_delete=models.CASCADE,
    )
    kind = models.CharField("نوع", max_length=20, choices=Kind.choices)
    object_id = models.PositiveIntegerField("شناسه")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "kind", "object_id"], name="unique_bookmark"),
        ]
        ordering = ["-created_at"]
        verbose_name = "ذخیره"
        verbose_name_plural = "ذخیره‌ها"

    def __str__(self):
        return f"{self.user_id} {self.kind} {self.object_id}"
