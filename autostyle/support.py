"""The optional Buy Me a Coffee link (modelled on Roat's Law 8).

Virten Studio never asks for money: no pop-ups, nag screens, counters, timers, unlock codes or supporter modes, and
nothing is gated, delayed, degraded or watermarked. The link is a static button (Settings ▸ Support Virten Studio and
the sidebar footer) that opens SUPPORT_URL in the browser, only when clicked. No supporter state is stored and nothing
is sent anywhere."""
import urllib.parse
import webbrowser

SUPPORT_URL = "https://buymeacoffee.com/roat"
_ALLOWED_HOSTS = ("buymeacoffee.com", "www.buymeacoffee.com")


def _is_support_url(url):
    """Only https://buymeacoffee.com/... (no other scheme, host, port or credentials)."""
    try:
        u = urllib.parse.urlsplit(url)
    except (TypeError, ValueError):
        return False
    return (u.scheme == "https" and (u.hostname or "") in _ALLOWED_HOSTS and u.port is None
            and not u.username and not u.password and u.netloc in _ALLOWED_HOSTS)


def open_support_page():
    """Opens the Buy Me a Coffee page in the default browser. Takes no arguments, so no other address can be passed
    in; SUPPORT_URL itself is checked before it's opened. Returns True when the browser was asked to open it."""
    if not _is_support_url(SUPPORT_URL):
        return False
    return bool(webbrowser.open(SUPPORT_URL))
