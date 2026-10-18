import re
from io import BytesIO
from pathlib import Path

from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ImageOps

from talent.models import (
    Banner,
    BlogCategory,
    Category,
    JobPost,
    Photo,
    Post,
    Profile,
    Rating,
    ResumeItem,
    Role,
    IdentityDocument,
)
from talent.cities import CITY_OF, city_choices
from talent.html_text import sanitize_html
from talent.provinces import province_choices


class CitySelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        province = CITY_OF.get(str(option["value"]))
        if province:
            option["attrs"]["data-province"] = province
        return option

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_password(value):
    """رقم فارسی/عربی را به لاتین تبدیل می‌کند تا رمز سادهٔ عددی درست ذخیره شود."""
    return (value or "").translate(PERSIAN_DIGITS)


class SimplePasswordChangeForm(PasswordChangeForm):
    """رمز ساده حداقل ۴ کاراکتر (مثل ۶ رقم) بدون قوانین پیچیدگی."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tip = "رمز ساده کافی است؛ حداقل ۴ رقم یا حرف (مثل ۱۲۳۴۵۶)."
        for name in ("old_password", "new_password1", "new_password2"):
            self.fields[name].help_text = tip if name == "new_password1" else ""
            self.fields[name].widget.attrs.update(
                {"autocomplete": "new-password" if name != "old_password" else "current-password"}
            )

    def clean_old_password(self):
        self.cleaned_data["old_password"] = normalize_password(self.cleaned_data.get("old_password"))
        return super().clean_old_password()

    def clean_new_password1(self):
        password = normalize_password(self.cleaned_data.get("new_password1"))
        self.cleaned_data["new_password1"] = password
        return password

    def clean_new_password2(self):
        password1 = normalize_password(self.cleaned_data.get("new_password1"))
        password2 = normalize_password(self.cleaned_data.get("new_password2"))
        self.cleaned_data["new_password1"] = password1
        self.cleaned_data["new_password2"] = password2
        return super().clean_new_password2()


def normalize_phone(value):
    value = (value or "").translate(PERSIAN_DIGITS)
    return re.sub(r"[\s\-()]", "", value)


def validate_phone(value):
    phone = normalize_phone(value)
    if phone.startswith("+98"):
        phone = "0" + phone[3:]
    elif phone.startswith("0098"):
        phone = "0" + phone[4:]
    elif phone.startswith("98") and len(phone) == 12:
        phone = "0" + phone[2:]
    if not re.fullmatch(r"09\d{9}", phone):
        raise forms.ValidationError("شماره موبایل را درست وارد کنید. مثال: 09121234567")
    return phone


def phone_lookup_keys(phone):
    """همه شکل‌های رایج یک شماره برای جستجوی تکراری."""
    phone = validate_phone(phone)
    local = phone[1:]  # 9xxxxxxxxx
    keys = {
        phone,
        local,
        f"+98{local}",
        f"0098{local}",
        f"98{local}",
    }
    persian = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    keys.update({key.translate(persian) for key in list(keys)})
    return keys


def accounts_for_phone(phone, user=None):
    keys = phone_lookup_keys(phone)
    profiles = (
        Profile.objects.filter(phone__in=keys)
        .select_related("user")
        .order_by("id")
    )
    if user is not None:
        profiles = profiles.exclude(user=user)
    found = []
    seen = set()
    for profile in profiles:
        if profile.user_id in seen:
            continue
        seen.add(profile.user_id)
        found.append(profile.user)
    matches = User.objects.filter(username__in=keys).order_by("id")
    if user is not None:
        matches = matches.exclude(pk=user.pk)
    for account in matches:
        if account.pk in seen:
            continue
        seen.add(account.pk)
        found.append(account)
    return found


def phone_taken(phone, user=None):
    return bool(accounts_for_phone(phone, user))


def validate_contact_phone(value):
    raw = (value or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) >= 11:
        digits = "0" + digits[2:]
    if not re.fullmatch(r"0\d{7,10}", digits):
        raise forms.ValidationError("شماره تماس را با صفر اول بنویس. مثلاً ۰۲۱ یا ۰۹۱۲.")
    return digits


UPLOAD_MAX_BYTES = 15 * 1024 * 1024
IDENTITY_MAX_BYTES = 4 * 1024 * 1024
IDENTITY_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
WELCOME_MAX_BYTES = 8 * 1024 * 1024
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".ogg", ".wav"}
VIDEO_EXTENSIONS = {".mp4", ".webm"}
IMAGE_LIMIT_TEXT = "JPG، PNG یا WEBP. اندازه و حجم را خود سایت تنظیم می‌کند."
BANNER_SIZE_TEXT = (
    "صفحه اول به ۱۲۰۰ در ۳۰۰ پیکسل تنظیم می‌شود. "
    "بنر دسته و بلاگ به ۵۶۰ در ۱۶۰ پیکسل تنظیم می‌شود. "
    "فرمت JPG، PNG یا WEBP."
)
POST_COVER_SIZE_TEXT = (
    "تصویر کنار نوشته به ۸۰۰ در ۴۵۰ پیکسل تنظیم می‌شود. "
    "فرمت JPG، PNG یا WEBP."
)


def _open_image(upload):
    if getattr(upload, "size", 0) > UPLOAD_MAX_BYTES:
        raise forms.ValidationError("حجم فایل خیلی زیاد است. عکس را کوچک‌تر بفرست.")
    try:
        probe = Image.open(upload)
        image_format = probe.format
        probe.verify()
        upload.seek(0)
        image = ImageOps.exif_transpose(Image.open(upload))
        image.load()
    except forms.ValidationError:
        raise
    except Exception as exc:
        raise forms.ValidationError("این فایل عکس سالم نیست.") from exc
    if image_format not in {"JPEG", "PNG", "WEBP"}:
        raise forms.ValidationError("فقط عکس JPG، PNG یا WEBP مجاز است.")
    upload.seek(0)
    return image


def _to_rgb(image):
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        base = Image.new("RGB", rgba.size, (255, 255, 255))
        base.paste(rgba, mask=rgba.split()[-1])
        return base
    return image.convert("RGB")


def _jpeg_bytes(image, max_bytes):
    quality = 85
    data = b""
    current = image
    while True:
        buffer = BytesIO()
        current.save(buffer, format="JPEG", quality=quality, optimize=True)
        data = buffer.getvalue()
        if len(data) <= max_bytes or (quality <= 45 and min(current.size) <= 480):
            return data
        if quality > 45:
            quality -= 10
            continue
        width = max(int(current.size[0] * 0.8), 1)
        height = max(int(current.size[1] * 0.8), 1)
        current = current.resize((width, height), Image.Resampling.LANCZOS)


def prepare_image(upload, max_width, max_height, max_bytes, cover=False):
    if not upload:
        return upload
    if not isinstance(upload, UploadedFile):
        return upload
    image = _to_rgb(_open_image(upload))
    if cover:
        image = ImageOps.fit(image, (max_width, max_height), method=Image.Resampling.LANCZOS)
    else:
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    data = _jpeg_bytes(image, max_bytes)
    stem = Path(getattr(upload, "name", "") or "photo").stem or "photo"
    return ContentFile(data, name=f"{stem}.jpg")


def validate_image(image):
    return prepare_image(image, 1600, 1600, 400 * 1024)


class PhoneStartForm(forms.Form):
    phone = forms.CharField(label="شماره موبایل", max_length=20)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel", "placeholder": "09121234567"}
        )
        self.fields["phone"].help_text = "هر شماره فقط یک حساب دارد. اگر قبلاً آمده‌ای، همان حساب باز می‌شود."

    def clean_phone(self):
        return validate_phone(self.cleaned_data["phone"])


class ForgotUsernameForm(PhoneStartForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].help_text = (
            "اول کد تایید پیامک می‌شود؛ بعد نام کاربری‌ات را همان‌جا و در پیامک می‌فرستیم."
        )


class LoginForm(forms.Form):
    phone = forms.CharField(label="شماره موبایل", max_length=20)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel", "placeholder": "09121234567"}
        )
        self.fields["phone"].help_text = "هر شماره فقط یک حساب دارد."

    def clean_phone(self):
        return validate_phone(self.cleaned_data["phone"])


class StaffUserForm(forms.Form):
    display_name = forms.CharField(label="نام و نام خانوادگی", max_length=80)
    phone = forms.CharField(label="شماره موبایل", max_length=20)
    city = forms.ChoiceField(
        label="شهر",
        required=False,
        widget=CitySelect(attrs={"class": "pick-list"}),
    )
    roles = forms.ModelMultipleChoiceField(
        label="تخصص‌ها",
        queryset=Role.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "role-picks"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel", "placeholder": "09121234567"}
        )
        posted_city = self.data.get("city", "") if self.data else ""
        self.fields["city"].choices = city_choices(self.initial.get("city") or posted_city)
        self.fields["roles"].queryset = Role.objects.select_related("category").order_by(
            "category__name", "name"
        )
        self.fields["roles"].label_from_instance = (
            lambda role: f"{role.category.name} — {role.name}"
        )

    def clean_phone(self):
        phone = validate_phone(self.cleaned_data["phone"])
        if phone_taken(phone):
            raise forms.ValidationError("این شماره قبلاً ثبت شده.")
        return phone


class SupportAccountForm(forms.Form):
    display_name = forms.CharField(label="نام و نام خانوادگی", max_length=80)
    phone = forms.CharField(label="شماره موبایل", max_length=20)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["phone"].widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel", "placeholder": "09121234567", "dir": "ltr"}
        )

    def clean_phone(self):
        phone = validate_phone(self.cleaned_data["phone"])
        if phone_taken(phone, self.user):
            raise forms.ValidationError("این شماره قبلاً ثبت شده.")
        return phone


class VisitorAccountForm(forms.Form):
    display_name = forms.CharField(label="نام ویزیتور", max_length=80)
    phone = forms.CharField(label="شماره موبایل ویزیتور", max_length=20)
    city = forms.ChoiceField(label="شهر")
    about = forms.CharField(
        label="توضیحات",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["city"].choices = city_choices()
        self.fields["phone"].widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel", "placeholder": "09121234567", "dir": "ltr"}
        )

    def clean_phone(self):
        phone = validate_phone(self.cleaned_data["phone"])
        if phone_taken(phone, self.user):
            raise forms.ValidationError("این شماره قبلاً ثبت شده.")
        return phone


class SignupForm(forms.Form):
    display_name = forms.CharField(label="نام و نام خانوادگی", max_length=80)
    phone = forms.CharField(label="شماره موبایل", max_length=20)
    accepted = forms.BooleanField(
        label="قبول شرایط استفاده",
        required=True,
        error_messages={"required": "برای ثبت‌نام باید شرایط استفاده را بپذیری."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel", "placeholder": "09121234567"}
        )

    def clean_phone(self):
        phone = validate_phone(self.cleaned_data["phone"])
        if phone_taken(phone):
            raise forms.ValidationError(
                "این شماره قبلاً ثبت شده و فقط یک حساب دارد. از صفحه ورود استفاده کن."
            )
        return phone


class CodeForm(forms.Form):
    code = forms.CharField(label="کد ۴ رقمی", max_length=8)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].widget.attrs.update(
            {
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "autofocus": "autofocus",
                "placeholder": "۴ رقم",
                "maxlength": "4",
            }
        )

    def clean_code(self):
        code = normalize_phone(self.cleaned_data.get("code") or "")
        if not re.fullmatch(r"\d{4}", code):
            raise forms.ValidationError("کد ۴ رقمی پیامک‌شده را وارد کن.")
        return code


class SmsSettingForm(forms.Form):
    api_key = forms.CharField(
        label="کلید API کاوه‌نگار",
        required=False,
        widget=forms.PasswordInput(render_value=False),
    )
    template = forms.CharField(label="نام قالب اعتبارسنجی", max_length=80)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["api_key"].help_text = "اگر کلید قبلاً ذخیره شده، خالی بگذار تا همان بماند."
        self.fields["template"].help_text = (
            "در کاوه‌نگار یک قالب اعتبارسنجی بساز که متنش %token داشته باشد. "
            "نام همان قالب را اینجا بنویس، مثلاً login."
        )

    def clean_template(self):
        template = (self.cleaned_data.get("template") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", template):
            raise forms.ValidationError(
                "نام قالب را مثل پنل کاوه‌نگار بنویس: حروف انگلیسی، عدد، خط تیره یا زیرخط."
            )
        return template


class ProfileForm(forms.Form):
    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        kwargs.setdefault("auto_id", "profile_%s")
        super().__init__(*args, **kwargs)
        self.fields["province"].choices = province_choices(self.initial.get("province", ""))
        posted_city = self.data.get("city", "") if self.data else ""
        city_options = city_choices(self.initial.get("city") or posted_city)
        self.fields["city"].widget = CitySelect(attrs={
            "class": "pick-list",
            "data-province-select": "profile_province",
        })
        self.fields["city"].choices = city_options
        self.order_fields(
            [
                "avatar",
                "display_name",
                "username",
                "business_name",
                "province",
                "city",
                "address",
                "headline",
                "bio",
                "about_business",
                "phone",
                "contact_phone",
                "instagram",
                "telegram",
                "whatsapp",
                "website",
                "latitude",
                "longitude",
            ]
        )
        if self.user is not None and getattr(getattr(self.user, "profile", None), "phone", ""):
            self.fields["phone"].disabled = True
            self.fields["phone"].help_text = "شماره ورود را فقط مدیر می‌تواند عوض کند."
        self.fields["contact_phone"].widget.attrs["dir"] = "ltr"

    display_name = forms.CharField(label="نام و نام خانوادگی", max_length=80)
    username = forms.CharField(
        label="نام کاربری",
        max_length=150,
        required=False,
        help_text="اختیاری است و برای ورود لازم نیست.",
    )
    business_name = forms.CharField(label="نام مجموعه", max_length=120, required=False)
    province = forms.ChoiceField(label="استان", required=False)
    city = forms.ChoiceField(label="شهر", required=False)
    address = forms.CharField(label="آدرس", max_length=240, required=False)
    headline = forms.CharField(label="یک خط معرفی", max_length=140, required=False)
    bio = forms.CharField(label="معرفی خودت", widget=forms.Textarea, required=False)
    about_business = forms.CharField(
        label="معرفی مجموعه",
        widget=forms.Textarea,
        required=False,
    )
    phone = forms.CharField(label="شماره موبایل", max_length=20)
    contact_phone = forms.CharField(
        label="شماره‌ای که به کاربران نمایش داده می‌شود",
        max_length=20,
        required=False,
        help_text="این شماره بعد از تایید مدیر به کاربران نشان داده می‌شود. شماره ورود نیست.",
    )
    instagram = forms.CharField(label="اینستاگرام", max_length=200, required=False)
    telegram = forms.CharField(label="تلگرام", max_length=200, required=False)
    whatsapp = forms.CharField(label="واتساپ", max_length=200, required=False)
    website = forms.CharField(label="وب‌سایت", max_length=200, required=False)
    latitude = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        widget=forms.HiddenInput,
    )
    longitude = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        widget=forms.HiddenInput,
    )
    avatar = forms.ImageField(
        label="عوض کردن عکس چهره",
        required=False,
        help_text="همین عکس روی کارت تو دیده می‌شود. " + IMAGE_LIMIT_TEXT,
    )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            return ""
        UnicodeUsernameValidator()(username)
        if re.fullmatch(r"09\d{9}", username):
            raise forms.ValidationError("نام کاربری نباید شماره موبایل باشد.")
        taken = User.objects.filter(username__iexact=username)
        if self.user is not None:
            taken = taken.exclude(pk=self.user.pk)
        if taken.exists():
            raise forms.ValidationError("این نام کاربری قبلاً گرفته شده.")
        return username

    def clean_phone(self):
        current = ""
        if self.user is not None:
            current = getattr(getattr(self.user, "profile", None), "phone", "") or ""
        if current:
            return current
        phone = validate_phone(self.cleaned_data["phone"])
        if phone_taken(phone, self.user):
            raise forms.ValidationError("این شماره قبلاً ثبت شده. هر شماره فقط یک حساب دارد.")
        return phone

    def clean_contact_phone(self):
        return validate_contact_phone(self.cleaned_data.get("contact_phone"))

    def clean_avatar(self):
        return prepare_image(self.cleaned_data.get("avatar"), 800, 800, 220 * 1024)


class VisitorRecruitForm(ProfileForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["city"].choices = self.fields["city"].choices
        self.fields["phone"].widget.attrs["dir"] = "ltr"

    def clean_phone(self):
        phone = validate_phone(self.cleaned_data.get("phone"))
        if phone_taken(phone):
            raise forms.ValidationError("این شماره قبلاً ثبت شده. شماره تکراری یا حساب موجود پذیرفته نمی‌شود.")
        return phone


class PhotoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "photo_%s")
        super().__init__(*args, **kwargs)

    class Meta:
        model = Photo
        fields = ("image", "caption")
        labels = {"image": "عکس", "caption": "توضیح کوتاه"}
        help_texts = {"image": IMAGE_LIMIT_TEXT}

    def clean_image(self):
        return validate_image(self.cleaned_data.get("image"))


class ResumeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "resume_%s")
        super().__init__(*args, **kwargs)

    class Meta:
        model = ResumeItem
        fields = ("title", "role_name", "year", "description")
        labels = {
            "title": "نام کار",
            "role_name": "سمت شما",
            "year": "سال",
            "description": "توضیح",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class SubcategoryForm(forms.Form):
    name = forms.CharField(label="نام دسته یا زیرمجموعه", max_length=80)
    parent = forms.ModelChoiceField(
        label="زیرمجموعهٔ این دسته باشد",
        queryset=Category.objects.all(),
        required=False,
        help_text="اگر خالی بماند، یک دسته اصلی ساخته می‌شود. برای لپ‌تاپ و مانند آن، دسته مادر را «تعمیرات آی‌تی» بگذار.",
    )

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("نام را بنویس.")
        return name

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get("name")
        parent = cleaned.get("parent")
        if name and Category.objects.filter(name=name, parent=parent).exists():
            self.add_error("name", "این نام در همین سطح هست.")
        return cleaned


class NewCategoryForm(forms.Form):
    name = forms.CharField(label="نام دسته", max_length=80)

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("نام دسته را بنویس.")
        if Category.objects.filter(name=name, parent__isnull=True).exists():
            raise forms.ValidationError("این دسته اصلی هست.")
        return name


class JobForm(forms.ModelForm):
    kind = forms.ChoiceField(
        label="نوع آگهی",
        choices=JobPost.Kind.choices,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = JobPost
        fields = ("kind", "title", "category", "city", "duration_days", "body")
        labels = {
            "title": "عنوان",
            "category": "زمینه کار",
            "city": "شهر",
            "duration_days": "تا کی روی سایت بماند",
            "body": "شرح",
        }
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("عنوان آگهی را بنویس.")
        return title

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("شرح آگهی خالی است.")
        return body


class BlogCategoryForm(forms.ModelForm):
    class Meta:
        model = BlogCategory
        fields = ("name",)
        labels = {"name": "نام دسته"}

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("نام دسته را بنویس.")
        return name


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ("title", "cover", "category", "body", "is_published", "seo_title", "seo_description")
        labels = {
            "title": "عنوان",
            "cover": "تصویر نوشته",
            "seo_title": "عنوان گوگل",
            "seo_description": "توضیح گوگل",
            "category": "دسته",
            "body": "متن",
            "is_published": "در بلاگ نشان داده شود",
        }
        error_messages = {
            "seo_title": {"max_length": "عنوان گوگل حداکثر ۷۰ حرف است. حدود ۵۰ تا ۶۰ حرف بنویس."},
            "seo_description": {"max_length": "توضیح گوگل حداکثر ۱۷۰ حرف است. حدود ۱۲۰ تا ۱۶۰ حرف بنویس."},
        }
        widgets = {
            "seo_description": forms.Textarea(attrs={"rows": 3, "maxlength": "170"}),
            "body": forms.Textarea(
                attrs={
                    "rows": 14,
                    "placeholder": "<h2>تیتر</h2>\n<p>متن، <strong>درشت</strong> و <a href=\"https://example.com\">لینک</a></p>",
                }
            )
        }
        help_texts = {
            "cover": POST_COVER_SIZE_TEXT,
            "seo_title": "لینک آبی گوگل. حدود ۵۰ تا ۶۰ حرف. اگر خالی بماند از عنوان نوشته ساخته می‌شود.",
            "seo_description": "متن خاکستری زیر لینک. حدود ۱۲۰ تا ۱۶۰ حرف. شماره تلفن را ننویس. اگر خالی بماند از متن نوشته ساخته می‌شود.",
            "body": "می‌توانی HTML کامل، CSS، قالب و کلاس بنویسی. تگ style، template، section و ویژگی class و style قبول می‌شود. اسکریپت و کد خطرناک ذخیره نمی‌شود.",
        }

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("عنوان را بنویس.")
        return title

    def clean_cover(self):
        cover = self.cleaned_data.get("cover")
        if isinstance(cover, UploadedFile):
            return prepare_image(cover, 800, 450, 180 * 1024, cover=True)
        return cover

    def clean_seo_title(self):
        return " ".join((self.cleaned_data.get("seo_title") or "").split())

    def clean_seo_description(self):
        return " ".join((self.cleaned_data.get("seo_description") or "").split())

    def clean_body(self):
        body = sanitize_html((self.cleaned_data.get("body") or "").strip())
        visible = body.replace("<br>", "").replace("<hr>", "")
        if "<img" not in body and "<video" not in body and not re.sub(r"<[^>]+>", "", visible).strip():
            raise forms.ValidationError("متن نوشته خالی است.")
        return body


class GroupMessageForm(forms.Form):
    category = forms.ChoiceField(label="دسته")
    body = forms.CharField(
        label="متن پیام",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="برای متخصص‌های تاییدشده این دسته و زیرمجموعه‌هایش فرستاده می‌شود و در پیام‌هایشان می‌آید.",
    )

    def __init__(self, *args, category_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = category_choices or []

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("متن پیام خالی است.")
        return body


class TicketForm(forms.Form):
    subject = forms.CharField(label="موضوع", max_length=120)
    body = forms.CharField(
        label="شرح",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="این پیام فقط برای مدیر و پشتیبان است.",
    )

    def clean_subject(self):
        subject = self.cleaned_data["subject"].strip()
        if not subject:
            raise forms.ValidationError("موضوع را بنویس.")
        return subject

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("شرح تیکت خالی است.")
        return body


class TicketReplyForm(forms.Form):
    reply = forms.CharField(
        label="پاسخ",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean_reply(self):
        reply = self.cleaned_data["reply"].strip()
        if not reply:
            raise forms.ValidationError("پاسخ خالی است.")
        return reply


class ViolationForm(forms.Form):
    reason = forms.ChoiceField(label="نوع تخلف", choices=[])
    body = forms.CharField(
        label="شرح",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="چه چیزی دیدی؟ مدیر همین شرح را می‌خواند.",
    )

    def __init__(self, *args, reason_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].choices = reason_choices or []

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("شرح تخلف خالی است.")
        return body


class MessageForm(forms.Form):
    body = forms.CharField(
        label="پیام",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("متن پیام خالی است.")
        return body


class BannerForm(forms.ModelForm):
    class Meta:
        model = Banner
        fields = ("title", "image", "link", "place", "category")
        labels = {
            "title": "عنوان",
            "image": "عکس بنر",
            "link": "لینک",
            "place": "جای نمایش",
            "category": "بخش",
        }
        help_texts = {
            "title": "اختیاری است. اگر عکس باز نشود، همین متن دیده می‌شود.",
            "link": "آدرس کامل را بنویس. مثال: https://example.com",
            "image": BANNER_SIZE_TEXT,
            "place": "صفحه اول سه بنر چرخشی دارد. داخل هر دسته و در بلاگ دو بنر کوچک کنار هم است.",
            "category": "فقط برای بنر داخل دسته لازم است. صفحه اول و بلاگ را خالی بگذار.",
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if isinstance(image, UploadedFile):
            _open_image(image)
        return image

    def clean_place(self):
        return self.cleaned_data.get("place") or Banner.Place.HOME

    def clean(self):
        cleaned = super().clean()
        place = cleaned.get("place") or Banner.Place.HOME
        category = cleaned.get("category")
        image = cleaned.get("image")
        if isinstance(image, UploadedFile):
            if place == Banner.Place.HOME:
                cleaned["image"] = prepare_image(image, 1200, 300, 280 * 1024, cover=True)
            else:
                cleaned["image"] = prepare_image(image, 560, 160, 140 * 1024, cover=True)
        if place == Banner.Place.HOME:
            cleaned["category"] = None
            if not self.instance.pk and Banner.objects.filter(place=Banner.Place.HOME).count() >= 3:
                raise forms.ValidationError("۳ بنر پر شده است. برای بنر جدید صفحه اول، یکی را حذف کن.")
        elif place == Banner.Place.BLOG:
            cleaned["category"] = None
            if not self.instance.pk and Banner.objects.filter(place=Banner.Place.BLOG).count() >= 2:
                self.add_error("place", "بلاگ دو بنر دارد. برای عوض کردن، یکی را حذف کن.")
        else:
            if category is None:
                self.add_error("category", "برای بنر داخل دسته، همان دسته را انتخاب کن.")
            elif (
                not self.instance.pk
                and Banner.objects.filter(place=Banner.Place.SECTION, category=category).count() >= 2
            ):
                self.add_error("category", "این دسته دو بنر کوچک دارد. برای عوض کردن، یکی را حذف کن.")
        return cleaned


class PostCommentForm(forms.Form):
    score = forms.ChoiceField(
        label="امتیاز",
        required=False,
        choices=[(str(n), "۰۱۲۳۴۵"[n]) for n in range(1, 6)],
        widget=forms.RadioSelect,
    )
    body = forms.CharField(
        label="نظر",
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "نظرت را بنویس"}),
    )

    def clean_score(self):
        raw = (self.cleaned_data.get("score") or "").strip()
        if not raw:
            return None
        score = int(raw)
        if score < 1 or score > 5:
            raise forms.ValidationError("امتیاز باید بین ۱ تا ۵ باشد.")
        return score

    def clean_body(self):
        return (self.cleaned_data.get("body") or "").strip()[:500]

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("score") and not cleaned.get("body"):
            raise forms.ValidationError("امتیاز را انتخاب کن یا یک نظر بنویس.")
        return cleaned


def validate_welcome_file(upload, kind):
    if not upload:
        return upload
    if upload.size > WELCOME_MAX_BYTES:
        raise forms.ValidationError("حجم فایل حداکثر ۸ مگابایت است تا سایت سنگین نشود.")
    ext = Path(upload.name).suffix.lower()
    allowed = AUDIO_EXTENSIONS if kind == "audio" else VIDEO_EXTENSIONS
    label = "صدا" if kind == "audio" else "ویدیو"
    if ext not in allowed:
        names = "، ".join(sorted(item.lstrip(".") for item in allowed))
        raise forms.ValidationError(f"برای {label} فقط این فرمت‌ها مجاز است: {names}")
    return upload


class WelcomeForm(forms.Form):
    def __init__(self, *args, note=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not note or not note.audio:
            self.fields.pop("clear_audio", None)
        if not note or not note.video:
            self.fields.pop("clear_video", None)
        self.fields["is_active"].initial = True if note is None else note.is_active

    is_active = forms.BooleanField(
        label="اطلاعیه روشن باشد",
        required=False,
        help_text="اگر خاموش باشد، هیچ‌کس آن را نمی‌بیند. متن ذخیره می‌ماند.",
    )
    body = forms.CharField(
        label="متن پیام",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="اختیاری است. اگر فقط صدا یا ویدیو می‌گذاری، متن لازم نیست.",
    )
    audio = forms.FileField(
        label="پیام صوتی",
        required=False,
        help_text="حداکثر ۸ مگابایت. mp3، m4a، ogg یا wav.",
    )
    video = forms.FileField(
        label="پیام تصویری",
        required=False,
        help_text="حداکثر ۸ مگابایت. mp4 یا webm.",
    )
    clear_audio = forms.BooleanField(label="حذف صدای فعلی", required=False)
    clear_video = forms.BooleanField(label="حذف ویدیوی فعلی", required=False)

    def clean_body(self):
        return (self.cleaned_data.get("body") or "").strip()

    def clean_audio(self):
        return validate_welcome_file(self.cleaned_data.get("audio"), "audio")

    def clean_video(self):
        return validate_welcome_file(self.cleaned_data.get("video"), "video")


class IdentityForm(forms.Form):
    kind = forms.ChoiceField(label="نوع مدرک", choices=IdentityDocument.Kind.choices)
    title = forms.CharField(
        label="عنوان مدرک دیگر",
        required=False,
        max_length=80,
        help_text="فقط اگر «مدرک دیگر» را انتخاب کردی بنویس. مثلاً پروانه کسب یا کارت مهارت.",
    )
    file = forms.FileField(
        label="فایل مدرک",
        help_text="JPG، PNG، WEBP یا PDF. عکس را سایت کوچک می‌کند. PDF حداکثر ۴ مگابایت است. این فایل برای بازدیدکننده‌ها باز نمی‌شود.",
    )

    def clean_title(self):
        return (self.cleaned_data.get("title") or "").strip()

    def clean_file(self):
        upload = self.cleaned_data["file"]
        suffix = Path(upload.name or "").suffix.lower()
        if suffix not in IDENTITY_EXTENSIONS:
            raise forms.ValidationError("فقط JPG، PNG، WEBP یا PDF پذیرفته می‌شود.")
        if suffix == ".pdf":
            if upload.size > IDENTITY_MAX_BYTES:
                raise forms.ValidationError("حجم PDF حداکثر ۴ مگابایت است.")
            header = upload.read(5)
            upload.seek(0)
            if not header.startswith(b"%PDF-"):
                raise forms.ValidationError("این فایل PDF سالم نیست.")
            return upload
        return prepare_image(upload, 2000, 2000, 700 * 1024)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") == IdentityDocument.Kind.OTHER and not cleaned.get("title"):
            self.add_error("title", "برای مدرک دیگر یک عنوان بنویس.")
        return cleaned


def store_visit_file(upload):
    if not upload:
        raise forms.ValidationError("فایل را انتخاب کن.")
    suffix = Path(upload.name or "").suffix.lower()
    if suffix not in IDENTITY_EXTENSIONS:
        raise forms.ValidationError("فقط JPG، PNG، WEBP یا PDF پذیرفته می‌شود.")
    if suffix == ".pdf":
        if upload.size > IDENTITY_MAX_BYTES:
            raise forms.ValidationError("حجم PDF حداکثر ۴ مگابایت است.")
        header = upload.read(5)
        upload.seek(0)
        if not header.startswith(b"%PDF-"):
            raise forms.ValidationError("این فایل PDF سالم نیست.")
        return upload
    return prepare_image(upload, 2000, 2000, 700 * 1024)


class ChargeForm(forms.Form):
    amount = forms.IntegerField(
        label="مبلغ شارژ به تومان",
        min_value=10_000,
        max_value=50_000_000,
        help_text="پول را به مدیر می‌دهی. بعد از تایید او، همین مبلغ به کیف پول اضافه می‌شود.",
    )


class RatingForm(forms.ModelForm):
    class Meta:
        model = Rating
        fields = ("score", "comment")
        labels = {"score": "امتیاز", "comment": "نظر"}
        widgets = {
            "score": forms.RadioSelect(choices=[(n, "۰۱۲۳۴۵"[n]) for n in range(1, 6)]),
            "comment": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_score(self):
        score = self.cleaned_data["score"]
        if score < 1 or score > 5:
            raise forms.ValidationError("امتیاز باید بین ۱ تا ۵ باشد.")
        return score

    def clean_comment(self):
        return (self.cleaned_data.get("comment") or "").strip()[:500]
