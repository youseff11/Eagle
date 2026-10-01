"""
ASGI config for Core project.

Plain HTTP is handled by Django exactly as under WSGI. The one addition is
``/ws/events/``: a WebSocket that is only ever accepted from an allowed host
(``AllowedHostsOriginValidator`` - a request without an Origin header, which a
browser always sends, is refused) and only for a logged-in session (the
sign-in check sits on the route, in ``dashboard/routing.py``).

It exposes the ASGI callable as a module-level variable named ``application``.
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Core.settings')

from django.core.asgi import get_asgi_application  # noqa: E402

# Django must be set up before anything below imports a model.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from dashboard.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
})
