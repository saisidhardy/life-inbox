"""Authentication helpers for Life Inbox.

Provides single-user token authentication via the APP_TOKEN environment variable.
Enforced on all /api/* routes except /api/health.
"""

import os
import secrets
from typing import Optional

from fastapi import Request


def get_configured_app_token() -> Optional[str]:
    """Retrieve the configured APP_TOKEN, or None if authentication is disabled."""
    token = os.getenv("APP_TOKEN", "").strip()
    return token if token else None


def extract_token_from_request(request: Request) -> Optional[str]:
    """Extract token from Authorization header, X-App-Token header, or query param."""
    # 1. Authorization header (Bearer or raw token)
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token.strip()
        if not scheme.lower() == "bearer" and not token:
            return auth_header.strip()

    # 2. X-App-Token header
    x_token = request.headers.get("X-App-Token")
    if x_token:
        return x_token.strip()

    # 3. Query parameter (e.g. /api/export?token=...)
    query_token = request.query_params.get("token")
    if query_token:
        return query_token.strip()

    return None


def is_authenticated_request(request: Request) -> bool:
    """Check if the incoming request satisfies configured APP_TOKEN requirements.

    If APP_TOKEN is not set or empty, authentication is disabled (local dev/tests).
    """
    configured_token = get_configured_app_token()
    if not configured_token:
        return True

    provided_token = extract_token_from_request(request)
    if not provided_token:
        return False

    return secrets.compare_digest(provided_token, configured_token)
