from talent.models import HomeCopy

DEFAULTS = {
    "eyebrow": "تعمیر و آموزش",
    "headline": "متخصص تعمیر لپ‌تاپ و کامپیوتر را پیدا کن.",
    "lead": "لپ‌تاپ، کامپیوتر و ماشین اداری؛ هر متخصص صفحه خودش را دارد با عکس، معرفی، آدرس و موقعیت. با نام، تخصص، شهر یا فاصله جستجو کن.",
    "section_link": "دیدن متخصص‌های این بخش",
    "empty_people": "هنوز متخصص تاییدشده‌ای در فهرست نیست.",
    "jobs_title": "استخدام و نیاز به کار",
    "jobs_lead": "اگر نیرو می‌خواهی آگهی استخدام بگذار. اگر دنبال کار هستی، نیازت را بنویس. هر آگهی بعد از تایید مدیر دیده می‌شود.",
    "empty_jobs": "هنوز آگهی تاییدشده‌ای نیست.",
    "jobs_button": "دیدن آگهی‌ها و ثبت آگهی",
    "footer": "فیکسوگرام جای پیدا کردن متخصص تعمیر و آموزش است: لپ‌تاپ، آل‌این‌وان، مانیتور، کامپیوتر و ماشین‌های اداری. صفحه عمومی و هر پیام با تایید مدیر یا پشتیبان باز می‌شود.",
}

LABELS = {
    "eyebrow": "برچسب بالای عنوان",
    "headline": "عنوان اصلی",
    "lead": "توضیح زیر عنوان",
    "section_link": "متن لینک هر بخش",
    "empty_people": "وقتی متخصصی در فهرست نیست",
    "jobs_title": "عنوان بخش استخدام",
    "jobs_lead": "توضیح بخش استخدام",
    "empty_jobs": "وقتی آگهی نیست",
    "jobs_button": "دکمه آگهی‌ها",
    "footer": "متن پایین صفحه",
}

LONG = {"lead", "jobs_lead", "footer"}


def home_lines():
    row = HomeCopy.objects.order_by("pk").first()
    lines = {}
    for key, default in DEFAULTS.items():
        saved = (getattr(row, key, "") or "").strip() if row is not None else ""
        lines[key] = saved or default
    return lines


def home_fields():
    lines = home_lines()
    return [
        {"key": key, "label": LABELS[key], "value": lines[key], "long": key in LONG}
        for key in DEFAULTS
    ]


def save_home_lines(post):
    row, _created = HomeCopy.objects.get_or_create(pk=1)
    for key in DEFAULTS:
        setattr(row, key, " ".join((post.get(key) or "").split()))
    row.save()


DEFAULT_JOB_WARNING = (
    "قبل از همکاری هویت طرف را بررسی کن. پیش‌پرداخت نفرست و قرار را در جای امن بگذار. "
    "اگر آگهی استخدام یا آماده به کار مشکوک بود، گزارش تخلف بده."
)


def job_warning_text():
    row = HomeCopy.objects.order_by("pk").first()
    saved = (row.job_warning or "").strip() if row is not None else ""
    return saved or DEFAULT_JOB_WARNING


def save_job_warning(post):
    row = HomeCopy.objects.order_by("pk").first()
    text = (post.get("job_warning") or "").strip()
    if row is None:
        HomeCopy.objects.create(job_warning=text)
        return
    row.job_warning = text
    row.save(update_fields=["job_warning"])
