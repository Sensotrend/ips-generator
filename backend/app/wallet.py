"""Digital-wallet export: ask a credential issuer to turn an approved IPS Bundle into an
OpenID4VCI credential offer (the URL a wallet scans as a QR code).

The issuer is the Findynet IPS demo (``POST /issue`` with ``{content, protocol}`` answering
``{url}``); the same call the demo web page makes. The browser cannot call it directly (no CORS),
so the API does it. The Bundle is PHI: it is sent only on an explicit user action and never logged.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings

PROTOCOL = "OPENID4VCI_FINAL1"


class WalletError(Exception):
    """The issuer failed or refused. The message never contains Bundle content."""


def request_credential_offer(
    bundle: dict[str, Any],
    settings: Settings,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Return the credential-offer URL for ``bundle``."""
    if not settings.wallet_issuer_url:
        raise WalletError("wallet export is not configured")
    try:
        with httpx.Client(timeout=settings.wallet_issuer_timeout_s, transport=transport) as client:
            response = client.post(
                settings.wallet_issuer_url,
                # The issuer expects the Bundle as a JSON *string* in ``content``.
                json={"content": json.dumps(bundle), "protocol": PROTOCOL},
                headers={"Accept": "application/json"},
            )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise WalletError("the credential issuer could not be reached") from exc
    url = body.get("url") if isinstance(body, dict) else None
    if response.status_code != 200 or not isinstance(url, str) or not url:
        raise WalletError("the credential issuer did not return an offer")
    return url
