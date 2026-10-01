"""The live dot went green, red, green: the Redis read timeout against the layer's own wait.

``channels_redis`` waits for a message with a blocking pop that lasts five seconds
(``RedisChannelLayer.brpop_timeout``), and Redis answers "nothing" when they are up. redis-py 8 puts
a five second limit on every read by default, so on an idle connection the limit and the wait ran
out together: "Timeout reading from ..." about every five seconds, the consumer died with the
exception, the browser's socket closed and reopened. Render installs the newest redis, so only
production showed it; the tests use an in-memory layer and the laptop has no Redis.

Two checks, because the first alone would pass for a number nobody tried:

* the project's own settings, read the way production reads them (``REDIS_URL`` set), name a read
  timeout comfortably above the layer's wait;
* a stand-in that answers a blocking pop the way Redis does - after the full wait - is asked through a
  client built from exactly those settings, and the answer arrives.
"""

import asyncio
import json
import os
import subprocess
import sys

from channels_redis.core import RedisChannelLayer
from django.conf import settings
from django.test import SimpleTestCase
from redis.asyncio import Redis

#: Redis answers a few milliseconds after its own timeout runs out.
REDIS_ANSWERS_AFTER = RedisChannelLayer.brpop_timeout + 0.05


def project_redis_host():
    """The one host the project's channel layer is configured with when ``REDIS_URL`` is set."""
    code = "import json, Core.settings as s; print(json.dumps(s.CHANNEL_LAYERS))"
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=settings.BASE_DIR, capture_output=True, text=True,
        env={**os.environ, "REDIS_URL": "redis://127.0.0.1:6379/0", "DJANGO_SETTINGS_MODULE": "Core.settings"},
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    layer = json.loads(proc.stdout.strip().splitlines()[-1])["default"]
    assert layer["BACKEND"] == "channels_redis.core.RedisChannelLayer", layer
    return layer["CONFIG"]["hosts"][0]


async def _read_command(reader):
    line = await reader.readline()
    if not line:
        return None
    parts = []
    for _ in range(int(line[1:])):
        size = int((await reader.readline())[1:])
        parts.append((await reader.readexactly(size + 2))[:-2])
    return parts


async def _redis_standin(reader, writer):
    """Enough of Redis for one blocking pop: it answers "nothing" once the full wait is over."""
    try:
        while (command := await _read_command(reader)) is not None:
            name = command[0].upper()
            if name in (b"BZPOPMIN", b"BRPOP", b"BLPOP"):
                await asyncio.sleep(REDIS_ANSWERS_AFTER)
                writer.write(b"*-1\r\n")
            elif name == b"HELLO":
                writer.write(b"-ERR unknown command 'HELLO'\r\n")
            else:
                writer.write(b"+OK\r\n")
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


class RedisLayerReadTimeoutTests(SimpleTestCase):
    def test_the_read_timeout_is_set_and_well_above_the_layers_own_wait(self):
        host = project_redis_host()
        self.assertIn("socket_timeout", host, "without it redis-py applies its own five second limit")
        self.assertGreaterEqual(host["socket_timeout"], RedisChannelLayer.brpop_timeout + 5)

    def test_an_idle_wait_for_a_message_is_answered_and_not_cut_off(self):
        host = project_redis_host()
        options = {key: value for key, value in host.items() if key != "address"}

        async def ask():
            server = await asyncio.start_server(_redis_standin, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            client = Redis(host="127.0.0.1", port=port, protocol=2, **options)
            try:
                # The same call the layer makes while it waits for a message. The outer limit only
                # keeps a broken setting from holding the suite up for as long as redis-py retries.
                return await asyncio.wait_for(
                    client.bzpopmin("asgi:specific.abc!def", timeout=RedisChannelLayer.brpop_timeout), 15
                )
            finally:
                server.close()
                try:
                    await asyncio.wait_for(client.aclose(), 3)
                except Exception:  # noqa: BLE001
                    pass

        self.assertIsNone(asyncio.run(ask()))

