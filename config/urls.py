from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "مدیریت فیکسوگرام"
admin.site.site_title = "فیکسوگرام"
admin.site.index_title = "تایید متخصص‌ها، پیام‌ها و بنرهای تبلیغ"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("talent.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
