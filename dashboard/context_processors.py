"""Template context for the pages that are still Django templates: sign-in, the public legal pages, the 403 page.

The app's own shell takes its language and theme from ``spa.py``. No query here: these pages are open to everyone, and a
person who is not signed in has only the cookie.
"""


def eagle(request):
    user = getattr(request, "user", None)
    lang = request.COOKIES.get("eagle_lang")
    theme = request.COOKIES.get("eagle_theme")
    if user is not None and user.is_authenticated:
        lang = lang or user.ui_lang
        theme = theme or user.ui_theme
    # A cookie is whatever the browser sends; only the two values the pages know are written into them.
    lang = lang if lang in ("ar", "en") else "ar"
    theme = theme if theme in ("dark", "light") else "dark"
    return {
        "eagle_lang": lang,
        "eagle_theme": theme,
        "eagle_dir": "rtl" if lang == "ar" else "ltr",
    }
