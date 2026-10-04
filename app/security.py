"""Authentication, cross-site request protection and security headers.

The pure helpers are separate from the middleware so they can be tested alone.
"""
from __future__ import annotations

import base64
import binascii
import hmac
from typing import Optional, Set, Tuple
from urllib.parse import urlparse

from . import config

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_PATHS = {"/health"}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
)


def parse_basic_auth(header: Optional[str]) -> Optional[Tuple[str, str]]:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    user, sep, password = decoded.partition(":")
    return (user, password) if sep else None


def credentials_match(given: Optional[Tuple[str, str]], user: str, password: str) -> bool:
    if given is None:
        return False
    user_ok = hmac.compare_digest(given[0].encode("utf-8"), user.encode("utf-8"))
    pass_ok = hmac.compare_digest(given[1].encode("utf-8"), password.encode("utf-8"))
    return user_ok and pass_ok


def is_cross_site(
    origin: Optional[str],
    host: Optional[str],
    sec_fetch_site: Optional[str] = None,
    allowed: Optional[Set[str]] = None,
) -> bool:
    """True when a state-changing request looks like it came from another site."""
    allowed = allowed or set()
    if origin:
        if origin.rstrip("/") in allowed:
            return False
        return urlparse(origin).netloc.lower() != (host or "").lower()
    return (sec_fetch_site or "").lower() == "cross-site"


def is_json(content_type: Optional[str]) -> bool:
    return (content_type or "").split(";")[0].strip().lower() == "application/json"


def install_security(app) -> None:
    from fastapi.responses import JSONResponse, Response

    @app.middleware("http")
    async def security_middleware(request, call_next):
        path = request.url.path
        if path not in PUBLIC_PATHS:
            if config.auth_enabled():
                given = parse_basic_auth(request.headers.get("authorization"))
                if not credentials_match(given, config.AUTH_USER, config.AUTH_PASSWORD):
                    return Response(
                        "Authentication required", status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="UK Accounts"'},
                    )
            if request.method in UNSAFE_METHODS:
                if is_cross_site(
                    request.headers.get("origin"), request.headers.get("host"),
                    request.headers.get("sec-fetch-site"), config.ALLOWED_ORIGINS,
                ):
                    return JSONResponse({"success": False, "error": "Cross-site request blocked"}, status_code=403)
                if path.startswith("/api/") and request.headers.get("content-length", "0") not in ("", "0") and not is_json(request.headers.get("content-type")):
                    return JSONResponse(
                        {"success": False, "error": "Content-Type must be application/json"}, status_code=415
                    )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", CSP)
        if not path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
