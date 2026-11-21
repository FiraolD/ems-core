from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:password_change_done")

    def form_valid(self, form):
        # Clear the flag on the same user object the form is about to save.
        self.request.user.must_change_password = False
        return super().form_valid(form)
