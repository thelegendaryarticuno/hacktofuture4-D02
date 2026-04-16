"""
Helpers for setting and clearing the PipelineIQ session cookie.
"""

from fastapi import Response

from config import settings


def set_session_cookie(response: Response, token: str) -> None:
    cookie_kwargs = {
        "key": "piq_session",
        "value": token,
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": "lax",
        "max_age": settings.SESSION_EXPIRY_DAYS * 86400,
    }
    if settings.COOKIE_DOMAIN:
        cookie_kwargs["domain"] = settings.COOKIE_DOMAIN

    response.set_cookie(**cookie_kwargs)


def clear_session_cookie(response: Response) -> None:
    cookie_kwargs = {
        "key": "piq_session",
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": "lax",
    }
    if settings.COOKIE_DOMAIN:
        cookie_kwargs["domain"] = settings.COOKIE_DOMAIN

    response.delete_cookie(**cookie_kwargs)
