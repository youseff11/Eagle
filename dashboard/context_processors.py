"""Template context shared by every Eagle page."""

from .models import AppSettings, Notification


def eagle(request):
    user = getattr(request, "user", None)
    conf = AppSettings.load()

    lang = request.COOKIES.get("eagle_lang")
    theme = request.COOKIES.get("eagle_theme")
    if user is not None and user.is_authenticated:
        lang = lang or user.ui_lang
        theme = theme or user.ui_theme

    unread = 0
    last_id = 0
    if user is not None and user.is_authenticated:
        unread = Notification.objects.filter(user=user, is_read=False).count()
        last_id = (
            Notification.objects.filter(user=user).order_by("-id")
            .values_list("id", flat=True).first() or 0
        )

    return {
        "eagle_conf": conf,
        "eagle_lang": lang or "ar",
        "eagle_theme": theme or "dark",
        "eagle_dir": "rtl" if (lang or "ar") == "ar" else "ltr",
        "eagle_unread": unread,
        "last_notification_id": last_id,
        "eagle_poll_ms": conf.poll_ms,
        "eagle_window": conf.response_window_seconds,
    }
