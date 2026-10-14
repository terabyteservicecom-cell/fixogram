from django.contrib import admin
from django.utils import timezone

from talent.models import (
    Banner,
    BlogCategory,
    ChargeRequest,
    Category,
    JobPost,
    PhoneRequest,
    Photo,
    Post,
    Profile,
    ProfileRole,
    Rating,
    ResumeItem,
    Role,
    WelcomeMessage,
)


@admin.action(description="تایید موارد انتخاب‌شده")
def approve_selected(modeladmin, request, queryset):
    queryset.update(status="approved")


@admin.action(description="رد موارد انتخاب‌شده")
def reject_selected(modeladmin, request, queryset):
    queryset.update(status="rejected")


class ProfileRoleInline(admin.TabularInline):
    model = ProfileRole
    extra = 0


class PhoneRequestInline(admin.TabularInline):
    model = PhoneRequest
    extra = 0
    fk_name = "profile"


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "city", "province", "account_status", "user", "phone")
    search_fields = ("display_name", "city", "province", "business_name", "user__username", "phone")
    list_filter = ("account_status", "is_support", "is_visitor", "province")
    exclude = ("visit_file",)
    inlines = [ProfileRoleInline, PhoneRequestInline]


@admin.register(ProfileRole)
class ProfileRoleAdmin(admin.ModelAdmin):
    list_display = ("profile", "role", "status")
    list_filter = ("status", "role__category")
    search_fields = ("profile__display_name", "role__name")
    actions = [approve_selected, reject_selected]


@admin.register(PhoneRequest)
class PhoneRequestAdmin(admin.ModelAdmin):
    list_display = ("requester", "profile", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("requester__username", "profile__display_name")
    actions = [approve_selected, reject_selected]

    def save_model(self, request, obj, form, change):
        if change and "status" in form.changed_data and obj.status != PhoneRequest.Status.PENDING:
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "order")
    list_filter = ("parent",)
    search_fields = ("name",)
    fields = ("name", "parent", "order")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "category")
    list_filter = ("category",)
    search_fields = ("name",)
    fields = ("name", "category")


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    fields = ("name", "order")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "created_at")
    list_filter = ("is_published", "category")
    search_fields = ("title", "body")
    fields = ("title", "category", "body", "is_published")


@admin.register(JobPost)
class JobPostAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "status", "city", "author", "created_at")
    list_filter = ("kind", "status", "category")
    search_fields = ("title", "body", "city", "author__username")
    actions = [approve_selected, reject_selected]


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("title", "place", "category", "link", "order", "is_active")
    list_filter = ("is_active", "place", "category")
    fields = ("title", "image", "link", "place", "category", "order", "is_active")


@admin.register(WelcomeMessage)
class WelcomeMessageAdmin(admin.ModelAdmin):
    fields = ("body", "audio", "video")


@admin.register(ChargeRequest)
class ChargeRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "status", "created_at")
    list_filter = ("status",)


admin.site.register(Photo)
admin.site.register(ResumeItem)
admin.site.register(Rating)
