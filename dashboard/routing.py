from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/events/", consumers.EventsConsumer.as_asgi()),
]
