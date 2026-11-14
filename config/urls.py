from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(request):
    return JsonResponse({"status": "ok", "service": "jarvis-mailer"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("auth/", include("accounts.urls")),
    path("api/assistant/", include("assistant.urls")),
    path("", include("mail.urls")),
]
