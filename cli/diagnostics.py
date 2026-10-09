"""Dependency and opt-in connection checks. Diagnostics never send email."""

import importlib
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from backend.config import SMTP_FROM, companion_settings
from backend.delivery import smtp_connection, submission_settings
from backend.errors import ArticleError


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None  # Never forward the bearer token away from loopback.


def check_health(token: str, origin: str) -> None:
    request = Request("http://127.0.0.1:8765/health", headers={
        "Authorization": f"Bearer {token}", "X-Article-To-Kindle-Origin": origin,
    })
    # Ignore proxy environment settings for this local-only authenticated probe.
    from urllib.request import ProxyHandler
    opener = build_opener(ProxyHandler({}), NoRedirects())
    try:
        with opener.open(request, timeout=3) as response:
            body = response.read(4097)
            if len(body) > 4096 or json.loads(body) != {"status": "ok"}:
                raise ArticleError("Unexpected companion health response.")
    except HTTPError as error:
        message = {401: "Pairing token rejected.", 403: "Extension origin rejected."}.get(error.code, f"Companion returned HTTP {error.code}.")
        raise ArticleError(message) from error
    except (URLError, OSError) as error:
        raise ArticleError("Companion unavailable. Start it with article-to-kindle serve.") from error
    except (ValueError, UnicodeError) as error:
        raise ArticleError("Unexpected companion health response.") from error


def diagnose(*, companion=False, smtp=False, smtp_login=False, recipient=None) -> list[dict]:
    checks = [{"name": "python", "ok": sys.version_info >= (3, 11),
               "message": f"{sys.version.split()[0]} (requires Python 3.11+)"}]
    for name in ("bs4", "readability", "latex2mathml", "PIL", "fastapi", "uvicorn"):
        try:
            module = importlib.import_module(name)
            checks.append({"name": name, "ok": True, "message": getattr(module, "__version__", "installed")})
        except (ImportError, OSError):
            checks.append({"name": name, "ok": False, "message": "Unavailable; reinstall article-to-kindle dependencies."})
    if companion:
        try:
            token, origin = companion_settings()
            check_health(token, origin)
            checks.append({"name": "companion", "ok": True, "message": "Pairing accepted at 127.0.0.1:8765; token redacted."})
        except ArticleError as error:
            checks.append({"name": "companion", "ok": False, "message": str(error)})
    if smtp:
        try:
            settings, port, _ = submission_settings(recipient)
            checks.append({"name": "smtp", "ok": True,
                           "message": f"Configured. Approve sender {settings[SMTP_FROM]} in Amazon Personal Document Settings; approval cannot be verified here."})
            if smtp_login:
                with smtp_connection(settings, port):
                    pass
                checks.append({"name": "smtp-login", "ok": True, "message": "TLS login accepted; no email sent."})
        except (ArticleError, OSError) as error:
            checks.append({"name": "smtp-login" if smtp_login else "smtp", "ok": False, "message": str(error)})
    return checks
