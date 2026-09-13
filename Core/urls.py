"""URL configuration for the Eagle project."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # Django's own admin — the escape hatch for deleting or fixing rows that the
    # dashboard has no screen for. It lives on the default path because that is
    # where its owner expects to find it; the login page is the only thing an
    # unauthenticated visitor can reach.
    path("admin/", admin.site.urls),

    # The path this used to live on, kept so old bookmarks still arrive.
    path("django-admin/", RedirectView.as_view(pattern_name="admin:index", permanent=False)),

    path("", include("dashboard.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
