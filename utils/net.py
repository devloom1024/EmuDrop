"""HTTP(S) proxy support for EmuDrop.

The single source of truth is ``assets/proxy.conf`` (a plain ``KEY=VALUE`` file
that is also shell-sourceable), so the Python application and the shell OTA
scripts always agree on one configuration.

* ``launch.sh`` sources the file before it runs ``app_ota.sh`` / ``db_ota.sh``,
  which is why ``curl`` picks the proxy up automatically.
* This module does the equivalent for the Python process: it hands the proxy to
  ``requests`` sessions and also exports the conventional environment variables
  as a safety net for any ``curl``/``subprocess`` call made from the app.

If the file is missing, disabled or incomplete the app silently falls back to a
direct connection - a broken proxy configuration must never brick the app.
"""

import logging
import os
import time
from urllib.parse import quote

import requests

from utils.config import Config

logger = logging.getLogger(__name__)

CONF_FILENAME = "proxy.conf"
CONF_PATH = os.path.join(Config.ASSETS_DIR, CONF_FILENAME)

DEFAULT_NO_PROXY = "localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8"

_state = {
    "loaded": False,
    "enabled": False,
    "url": "",
    "proxies": {},
}


def read_config(path=CONF_PATH):
    """Parse ``proxy.conf`` into a dict.

    Unknown keys are kept, ``#`` starts a comment and quotes are stripped so
    values can be written either bare (``HOST=10.0.0.5``) or quoted.
    """
    conf = {}
    if not os.path.isfile(path):
        return conf

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                conf[key.strip().upper()] = value.split(" #")[0].strip().strip('"').strip("'")
    except OSError as exc:  # unreadable file: stay on direct connection
        logger.warning(f"Proxy: cannot read {path}: {exc}")

    return conf


def build_url(conf):
    """Build the proxy URL from a parsed config (credentials are URL-encoded)."""
    host = conf.get("HOST", "").strip()
    port = conf.get("PORT", "").strip()
    if not host or not port:
        return ""

    scheme = conf.get("SCHEME", "http").strip() or "http"
    user = conf.get("USER", "").strip()
    password = conf.get("PASS", "").strip()

    auth = ""
    if user:
        auth = quote(user, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"

    return f"{scheme}://{auth}{host}:{port}"


def redact(url):
    """Hide credentials before a proxy URL reaches a log file."""
    if not url or "@" not in url:
        return url
    head, tail = url.rsplit("@", 1)
    if "://" in head:
        scheme = head.split("://", 1)[0]
        return f"{scheme}://***@{tail}"
    return "***" + "@" + tail


def configure(path=CONF_PATH, force=False):
    """Load the proxy configuration and export it to the process environment.

    Idempotent: returns early unless ``force`` is set, so it can be called both
    at startup and lazily from :func:`get_session`.
    """
    if _state["loaded"] and not force:
        return _state

    conf = read_config(path)
    enabled = conf.get("ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
    url = build_url(conf) if enabled else ""

    if not url:
        # Make sure a previously enabled proxy cannot leak into this process
        for key in ("http_proxy", "https_proxy", "all_proxy",
                    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            os.environ.pop(key, None)
        _state.update(loaded=True, enabled=False, url="", proxies={})
        if enabled:
            logger.warning("Proxy: ENABLED=1 but HOST/PORT missing, using direct connection")
        else:
            logger.info("Proxy: disabled, using direct connection")
        return _state

    no_proxy = conf.get("NO_PROXY", DEFAULT_NO_PROXY).strip() or DEFAULT_NO_PROXY

    os.environ.update(
        {
            "http_proxy": url,
            "https_proxy": url,
            "all_proxy": url,
            "HTTP_PROXY": url,
            "HTTPS_PROXY": url,
            "ALL_PROXY": url,
            "no_proxy": no_proxy,
            "NO_PROXY": no_proxy,
        }
    )

    _state.update(
        loaded=True,
        enabled=True,
        url=url,
        proxies={"http": url, "https": url},
    )
    logger.info(f"Proxy: enabled via {redact(url)} (no_proxy={no_proxy})")
    return _state


def is_enabled():
    return configure()["enabled"]


def get_session(verify=True):
    """Return a ``requests`` session routed through the configured proxy.

    The proxy is taken from the environment (set by :func:`configure`) rather
    than from ``Session.proxies`` on purpose: explicit session proxies take
    precedence over ``NO_PROXY``, so a bypass list would stop working. With
    environment proxies ``requests`` skips the hosts listed in ``NO_PROXY``
    exactly like ``curl`` does.
    """
    configure()
    session = requests.Session()
    session.verify = verify
    return session


CONF_TEMPLATE = """# EmuDrop proxy configuration
#
# Edited in-app: Platforms -> N (Network settings).
# launch.sh sources this same file so the OTA scripts (curl) use the proxy too.
# HTTP proxies only; percent-encode special characters in USER/PASS.

ENABLED={ENABLED}
SCHEME={SCHEME}
HOST={HOST}
PORT={PORT}
USER={USER}
PASS={PASS}
NO_PROXY={NO_PROXY}
"""


def current_config():
    """Return the raw configuration dictionary (used by the settings screen)."""
    conf = read_config()
    defaults = {
        "ENABLED": "0",
        "SCHEME": "http",
        "HOST": "",
        "PORT": "",
        "USER": "",
        "PASS": "",
        "NO_PROXY": DEFAULT_NO_PROXY,
    }
    for key, value in defaults.items():
        conf.setdefault(key, value)
    return conf


def save_config(conf, path=CONF_PATH):
    """Persist the configuration and reload it immediately.

    Returns True on success. The write is done through a temporary file so an
    interrupted save cannot leave a truncated config behind.
    """
    data = {key: str(conf.get(key, "") or "") for key in
            ("ENABLED", "SCHEME", "HOST", "PORT", "USER", "PASS", "NO_PROXY")}
    data["ENABLED"] = "1" if data["ENABLED"].strip().lower() in ("1", "true", "yes", "on") else "0"
    data["SCHEME"] = (data["SCHEME"] or "http").strip() or "http"
    data["NO_PROXY"] = data["NO_PROXY"] or DEFAULT_NO_PROXY

    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(CONF_TEMPLATE.format(**data))
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.error(f"Proxy: cannot save {path}: {exc}")
        return False

    configure(path=path, force=True)
    return True


def test_connection(timeout=8):
    """Round-trip a small request through the current configuration.

    Returns ``(ok, message)`` where message is safe to show in the UI.
    """
    started = time.time()
    try:
        session = get_session()
        response = session.get("https://api.github.com/zen", timeout=(4, timeout))
        elapsed_ms = (time.time() - started) * 1000
        if response.status_code == 200:
            return True, f"OK 200 in {elapsed_ms:.0f} ms"
        return False, f"HTTP {response.status_code} in {elapsed_ms:.0f} ms"
    except Exception as exc:  # noqa: BLE001 - any failure is a failed test
        elapsed_ms = (time.time() - started) * 1000
        return False, f"{type(exc).__name__} after {elapsed_ms:.0f} ms"
