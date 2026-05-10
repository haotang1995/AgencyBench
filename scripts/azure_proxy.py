#!/usr/bin/env python3
"""Tiny localhost reverse proxy that adds the X-API-Key header.

The Azure-hosted OAI-compat proxy at dwip-openai-...azurewebsites.net/v1
requires *both* `Authorization: Bearer <key>` and `X-API-Key: <key>`.
The SII bridge (Node) only sends the bearer, and worse, its URL string
contains "azure" so it switches to real-Azure OpenAI protocol (mangled
URL + api-key header). We avoid both problems by listening on
http://127.0.0.1:<port>/v1 and forwarding to the real endpoint with
X-API-Key spliced in.

Usage:
    python3 scripts/azure_proxy.py
    # default port 7333; override with PORT=...
"""

from __future__ import annotations

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import json
import httpx

UPSTREAM = os.environ.get(
    "AZURE_PROXY_UPSTREAM",
    "https://dwip-openai-ehe0b4f3cdctbfbp.westus2-01.azurewebsites.net",
).rstrip("/")
# Trailing /v1 (or any path) on the upstream is dropped — the request path
# from the client already carries /v1/chat/completions.
if UPSTREAM.endswith("/v1"):
    UPSTREAM = UPSTREAM[: -len("/v1")]
EXTRA_HEADER_KEY = os.environ.get("AZURE_PROXY_HEADER", "X-API-Key")
EXTRA_HEADER_VAL = os.environ.get("AZURE_PROXY_HEADER_VALUE") or os.environ.get(
    "X_API_KEY"
) or os.environ.get("OPENAI_API_KEY")
PORT = int(os.environ.get("PORT", "7333"))

if not EXTRA_HEADER_VAL:
    sys.exit("AZURE_PROXY_HEADER_VALUE / X_API_KEY / OPENAI_API_KEY not set")

# One shared client per process; httpx handles connection pooling + HTTP/1.1.
_client = httpx.Client(timeout=httpx.Timeout(connect=15, read=600, write=600, pool=15))


# max_completion_tokens cap for chat completions. The bridge hardcodes
# max_tokens=100000 (1e5), but gpt-4.1 caps at 32768 and gpt-5 rejects
# the older `max_tokens` field entirely. Rewrite to max_completion_tokens
# and clamp.
_MAX_COMPLETION_TOKENS_CAP = int(os.environ.get("AZURE_PROXY_MAX_TOKENS", "32768"))


# Aliases for models that the SII reference scenarios hardcode but
# our Azure proxy does not host (e.g. Research/scenario4 + scenario5
# subprocess-call --judge_model gzy/claude-4-sonnet for rubric recall
# scoring). Map to a real, reachable deployment instead of letting
# those scenarios 404.
_MODEL_ALIASES = {
    "gzy/claude-4-sonnet": "gpt-4.1",
    "gzy/claude-4.5-sonnet": "gpt-4.1",
    "gzy/claude-4.5-opus": "gpt-4.1",
    "gzy_claude-4-sonnet": "gpt-4.1",
    "gzy_claude-4.5-sonnet": "gpt-4.1",
    "gzy_claude-4.5-opus": "gpt-4.1",
    "claude-sonnet-4-5": "gpt-4.1",
    "claude-opus-4-5": "gpt-4.1",
}


def _rewrite_chat_body(raw: bytes) -> bytes:
    if not raw:
        return raw
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        return raw
    if not isinstance(body, dict):
        return raw
    changed = False
    model = body.get("model")
    if isinstance(model, str) and model in _MODEL_ALIASES:
        body["model"] = _MODEL_ALIASES[model]
        changed = True
    mt = body.pop("max_tokens", None)
    if mt is not None:
        body["max_completion_tokens"] = min(int(mt), _MAX_COMPLETION_TOKENS_CAP)
        changed = True
    mct = body.get("max_completion_tokens")
    if isinstance(mct, (int, float)) and mct > _MAX_COMPLETION_TOKENS_CAP:
        body["max_completion_tokens"] = _MAX_COMPLETION_TOKENS_CAP
        changed = True
    return json.dumps(body).encode("utf-8") if changed else raw


_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
    "host",
    "content-length",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[proxy] " + fmt % args + "\n")

    def _proxy(self, method: str) -> None:
        path = self.path  # already includes /v1/...
        url = f"{UPSTREAM}{path}"

        body = b""
        length = int(self.headers.get("Content-Length") or 0)
        if length > 0:
            body = self.rfile.read(length)

        if method == "POST" and "/chat/completions" in path:
            body = _rewrite_chat_body(body)

        headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP_BY_HOP}
        headers[EXTRA_HEADER_KEY] = EXTRA_HEADER_VAL
        if body:
            headers["Content-Length"] = str(len(body))

        try:
            with _client.stream(method, url, content=body, headers=headers) as r:
                self.send_response(r.status_code)
                for k, v in r.headers.items():
                    if k.lower() in _HOP_BY_HOP:
                        continue
                    self.send_header(k, v)
                self.end_headers()
                for chunk in r.iter_raw():
                    if not chunk:
                        continue
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
        except httpx.HTTPError as exc:
            msg = f'{{"error":"upstream {type(exc).__name__}: {exc}"}}'
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg.encode())

    def do_GET(self): self._proxy("GET")
    def do_POST(self): self._proxy("POST")
    def do_DELETE(self): self._proxy("DELETE")
    def do_PUT(self): self._proxy("PUT")
    def do_OPTIONS(self): self._proxy("OPTIONS")


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[proxy] listening on http://127.0.0.1:{PORT}  →  {UPSTREAM}", flush=True)
    print(f"[proxy] adding header {EXTRA_HEADER_KEY}: <redacted>", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
