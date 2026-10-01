from channels.auth import AuthMiddlewareStack
from django.urls import path, re_path

from . import consumers


async def _no_such_socket(scope, receive, send):
    """Any other WebSocket path: refused quietly, with no database work."""
    await receive()
    await send({"type": "websocket.close", "code": 4404})


# Sign-in is checked inside the route, not around the router, so a request for
# a path that is not ours is turned away before it costs a session lookup.
websocket_urlpatterns = [
    path("ws/events/", AuthMiddlewareStack(consumers.EventsConsumer.as_asgi())),
    re_path(r"^.*$", _no_such_socket),
]
