"""Outbound HTTP helper.

Some hosts (PythonAnywhere free accounts, corporate networks) only allow
outgoing HTTPS through a proxy. Set ``EAGLE_HTTPS_PROXY`` — for example
``http://proxy.server:3128`` on PythonAnywhere — and every call the dashboard
makes to the WhatsApp and Claude APIs goes through it. Left unset, requests go
out directly, which is what a normal server wants.
"""

import os
import urllib.request

PROXY_VARS = ("EAGLE_HTTPS_PROXY", "HTTPS_PROXY", "https_proxy")


def proxy_url():
    for name in PROXY_VARS:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return ""


def opener(*handlers):
    """A urllib opener that honours the configured proxy, if any. ``handlers`` are added to it (a redirect handler that
    keeps a request on one site, for one)."""
    proxy = proxy_url()
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}), *handlers
        )
    # ProxyHandler({}) disables urllib's implicit environment lookup so the
    # behaviour is identical whether or not the host exports proxy variables.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), *handlers)


def urlopen(request, timeout=60):
    return opener().open(request, timeout=timeout)
