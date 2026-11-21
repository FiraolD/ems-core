from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from core.audit.service import record

from .models import User


class EmsUserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User


class EmsUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = EmsUserChangeForm
    add_form = EmsUserCreationForm
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "must_change_password",
        "is_locked_now",
    )
    list_filter = (*BaseUserAdmin.list_filter, "must_change_password")
    fieldsets = (
        *BaseUserAdmin.fieldsets,
        (
            "Sign-in security",
            {
                "fields": (
                    "must_change_password",
                    "failed_login_count",
                    "locked_until",
                    "password_changed_at",
                )
            },
        ),
    )
    readonly_fields = ("failed_login_count", "password_changed_at")
    actions = ["unlock_accounts", "require_password_change"]

    @admin.display(boolean=True, description="Locked")
    def is_locked_now(self, obj):
        return obj.is_locked

    def save_model(self, request, obj, form, change):
        if not change:  # accounts an administrator creates start with a temporary password
            obj.must_change_password = True
        super().save_model(request, obj, form, change)

    def user_change_password(self, request, id, form_url=""):
        response = super().user_change_password(request, id, form_url)
        reset_done = request.method == "POST" and response.status_code == 302
        if reset_done and str(request.user.pk) != str(id):
            User.objects.filter(pk=id).update(must_change_password=True)
        return response

    @admin.action(description="Unlock selected accounts")
    def unlock_accounts(self, request, queryset):
        unlocked = 0
        for user in queryset:
            if user.locked_until or user.failed_login_count:
                User.objects.filter(pk=user.pk).update(failed_login_count=0, locked_until=None)
                record("account_unlocked", obj=user)
                unlocked += 1
        self.message_user(request, f"Unlocked {unlocked} account(s).", messages.SUCCESS)

    @admin.action(description="Require a password change at next sign-in")
    def require_password_change(self, request, queryset):
        for user in queryset:
            user.must_change_password = True
            user.save(update_fields=["must_change_password"])
        self.message_user(request, f"{queryset.count()} account(s) flagged.", messages.SUCCESS)
