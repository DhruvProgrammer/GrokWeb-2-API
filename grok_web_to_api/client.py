"""Async HTTP client for grok.com's internal web API.

The wire format we mirror:
  POST  https://grok.com/rest/app-chat/conversations/new
  Headers:
    content-type: application/json
    accept: text/event-stream
    origin: https://grok.com
    referer: https://grok.com/
    user-agent: <browser UA>
    x-statsig-id: <signed challenge>
    x-xai-request-id: <random>
    cookie: sso=..., sso-rw=...
  Body:
    {"temporary":true,"modelName":"auto","message":"...","fileAttachments":[],
     "imageAttachments":[],"disableSearch":false,"enableImageGeneration":false,
     "returnImageBytes":false,"returnRawGrokInXaiRequest":false,
     "enableImageStreaming":false,"imageGenerationCount":0,
     "forceConcise":false,"toolOverrides":{},"enableSideBySide":true,
     "isAsyncChat":true,"webpageUrls":null}

  Response: NDJSON-ish SSE stream of {"result":{"response":{"modelResponse":
    {"message":"<delta>","accumulatedMessage":"<running>","finalMessage":"..."}}}}
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from typing import AsyncIterator, Optional, Tuple

import httpx

from .challenge import ChallengeSigner
from .config import Settings

log = logging.getLogger(__name__)


def _new_request_id() -> str:
    """Per-request UUID-ish identifier; format isn't important to grok.com."""
    return secrets.token_hex(16)


class GrokError(Exception):
    """Raised when the upstream returns a non-2xx status."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"grok upstream {status}: {body[:200]}")


class GrokClient:
    """Async client wrapping grok.com's web API."""

    def __init__(self, settings: Settings, signer: ChallengeSigner):
        import os
        self._settings = settings
        self._signer = signer
        # Connection pool sized for typical single-user proxy use.
        # raise_app=False so we can decide ourselves how to surface errors.
        # Honor the standard CA-bundle env vars so the client works on
        # sandboxes that intercept TLS with their own CA (Aliyun, Azure,
        # k8s service-mesh sidecars, etc.) without forcing verify=False.
        verify: bool | str = True
        ca_bundle = (
            os.environ.get("SSL_CERT_FILE")
            or os.environ.get("REQUESTS_CA_BUNDLE")
            or os.environ.get("CURL_CA_BUNDLE")
        )
        if ca_bundle:
            verify = ca_bundle
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            verify=verify,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---- Cookie rotation --------------------------------------------------

    def set_cookies(self, sso: str, ssorw: str) -> None:
        """Hot-swap SSO values. Useful when a session expires."""
        self._settings.grok_sso_cookie = sso
        self._settings.grok_sso_rw_cookie = ssorw
        log.info("cookies rotated (sso=%d, sso-rw=%d chars)", len(sso), len(ssorw))

    # ---- Health probe -----------------------------------------------------

    async def health(self) -> Tuple[bool, str]:
        """Verify cookies are still valid by hitting a lightweight endpoint.

        Returns (ok, reason). Used by /health so the user can see
        "auth degraded" before a chat call starts failing.
        """
        url = f"{self._settings.grok_base_url}/rest/auth/session"
        try:
            resp = await self._http.get(
                url,
                headers=self._base_headers(),
                timeout=self._settings.health_timeout,
            )
            if resp.status_code in (401, 403):
                return False, f"auth rejected (HTTP {resp.status_code})"
            if resp.status_code >= 500:
                return False, f"upstream error (HTTP {resp.status_code})"
            return True, "ok"
        except httpx.HTTPError as e:
            return False, f"transport error: {e.__class__.__name__}"

    # ---- Chat -------------------------------------------------------------

    async def chat(
        self, model: str, message: str
    ) -> AsyncIterator[str]:
        """Stream one user turn and yield model text deltas.

        Raises GrokError on transport or upstream errors; the caller
        decides whether to surface the error to the client or to fold it
        into an SSE [ERROR] event.
        """
        url = f"{self._settings.grok_base_url}/rest/app-chat/conversations/new"
        body = self._build_request(model, message)
        headers = self._base_headers()

        # We need to read the response body as a stream, so use
        # stream() and iterate line-by-line. httpx doesn't expose a
        # streaming JSON decoder, so we do it ourselves.
        async with self._http.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                # Drain body so the connection can be reused, then raise.
                text = (await resp.aread()).decode("utf-8", errors="replace")
                raise GrokError(resp.status_code, text)

            last_message = ""
            async for line in resp.aiter_lines():
                if not line:
                    continue
                # Tolerate both bare JSON and "data: {json}" SSE framing.
                if line.startswith("data: "):
                    line = line[len("data: "):]
                if line == "[DONE]":
                    return

                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    # Unknown event shape - the browser does the same.
                    continue

                # Grok's modelResponse.message is the per-chunk delta.
                # accumulatedMessage is the running total. We always emit
                # the delta because that's what streaming clients expect.
                mr = (
                    parsed.get("result", {})
                    .get("response", {})
                    .get("modelResponse", {})
                )
                delta = mr.get("message") or ""
                if delta and delta != last_message:
                    # The first chunk often contains the whole reply in
                    # `accumulatedMessage` with `message` empty. Fall
                    # back to the running total so we still emit text.
                    yield delta
                    last_message = delta

    # ---- Helpers ----------------------------------------------------------

    def _build_request(self, model: str, message: str) -> dict:
        """Build the JSON body grok.com expects."""
        return {
            "temporary": self._settings.grok_temporary,
            "modelName": model,
            "message": message,
            "fileAttachments": [],
            "imageAttachments": [],
            "disableSearch": False,
            "enableImageGeneration": False,
            "returnImageBytes": False,
            "returnRawGrokInXaiRequest": False,
            "enableImageStreaming": False,
            "imageGenerationCount": 0,
            "forceConcise": False,
            "toolOverrides": {},
            "enableSideBySide": True,
            "isAsyncChat": True,
            "webpageUrls": None,
        }

    def _base_headers(self) -> dict:
        """Headers required by grok.com's web client to accept the request."""
        # Build the Cookie header. Cloudflare's cf_clearance is what gets
        # us past the "Just a moment..." challenge; cf_bm is the per-session
        # bot-management token. Both expire (~30 min) so the user must
        # refresh by reloading grok.com in a real browser periodically.
        cookie_parts = [
            f"sso={self._settings.grok_sso_cookie}",
            f"sso-rw={self._settings.grok_sso_rw_cookie}",
        ]
        if self._settings.grok_cf_clearance:
            cookie_parts.append(f"cf_clearance={self._settings.grok_cf_clearance}")
        if self._settings.grok_cf_bm:
            cookie_parts.append(f"__cf_bm={self._settings.grok_cf_bm}")
        return {
            "content-type": "application/json",
            "accept": "text/event-stream",
            "origin": self._settings.grok_origin,
            "referer": self._settings.grok_origin + "/",
            "user-agent": self._settings.grok_user_agent,
            "x-statsig-id": self._signer.sign(),
            "x-xai-request-id": _new_request_id(),
            "cookie": "; ".join(cookie_parts),
        }