#!/usr/bin/env python3
"""Tiny local relay so the live site's Cloudflare Worker can call the free
OpenCode Zen LLM without being throttled.

Why this exists: `platform/site/worker/ask.ts` calling
https://opencode.ai/zen/v1/chat/completions directly from Cloudflare Workers
comes back `FreeUsageLimitError` regardless of API key or free model — while
the exact same key from a residential connection (this machine, running
`scripts/rag_ask.py`) works fine. That points to OpenCode Zen throttling
Cloudflare's shared Workers egress IP range specifically, not the account.

This script runs a tiny HTTP server on *your* machine. The Worker calls it
(through a Cloudflare Tunnel, so it has a public URL) instead of calling
OpenCode Zen directly; this script then makes the actual OpenCode Zen call
from your residential IP and returns the answer.

Your OPENCODE_API_KEY never leaves this machine — it's read from an env var
here, never sent to or stored on Cloudflare. The Worker only needs a shared
secret (RELAY_SHARED_SECRET below) to authenticate its requests to this
relay; that secret is unrelated to, and much lower-stakes than, your OpenCode
API key.

Setup:
  1. export OPENCODE_API_KEY=...        # from https://opencode.ai/zen/
  2. export RELAY_SHARED_SECRET=...     # any random string, e.g.:
                                         #   python3 -c "import secrets; print(secrets.token_hex(24))"
  3. .venv/bin/python scripts/llm_relay.py
     -> starts on http://127.0.0.1:8799
  4. In another terminal, expose it publicly (installs cloudflared once via
     `brew install cloudflared` if you don't have it):
       cloudflared tunnel --url http://127.0.0.1:8799
     Copy the printed https://<random>.trycloudflare.com URL. It changes
     every time you restart the tunnel (quick/ephemeral tunnel, no domain
     required) — update the Worker secret below when it does.
  5. On the Worker side (from platform/site):
       npx wrangler secret put RELAY_URL
         -> paste https://<random>.trycloudflare.com/ask
       npx wrangler secret put RELAY_SHARED_SECRET
         -> paste the exact same value used in step 2

This machine and the `cloudflared` tunnel both need to stay running for the
live site's /assistant/ to work — see PROJECT_STATUS.md for this tradeoff
(chosen deliberately to keep the free model + avoid exposing the OpenCode key
to Cloudflare, at the cost of needing this machine reachable).

Only stdlib + `requests` are used (no fastapi/uvicorn dependency) so this
runs with a plain `python3`, no extra install beyond what scripts/rag_ask.py
already needs.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pdfkb.prompts import RAG_SYSTEM_PROMPT

API_URL = os.environ.get("RELAY_API_URL", "https://opencode.ai/zen/v1/chat/completions")
DEFAULT_MODEL = os.environ.get("RELAY_API_MODEL", "big-pickle")
HOST = os.environ.get("RELAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("RELAY_PORT", "8799"))

# Kept in sync by hand with FREE_MODELS in platform/site/worker/ask.ts — any
# model id the Worker is allowed to request must be whitelisted here too,
# since this relay is what actually calls OpenCode Zen.
FREE_MODEL_IDS = {
    "big-pickle",
    "deepseek-v4-flash-free",
    "mimo-v2.5-free",
    "hy3-free",
    "nemotron-3-ultra-free",
    "north-mini-code-free",
}


def resolve_model(requested: object) -> str:
    return requested if isinstance(requested, str) and requested in FREE_MODEL_IDS else DEFAULT_MODEL


def _env_or_exit(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"Erreur : variable d'environnement {name} manquante — voir l'en-tête de ce script.", file=sys.stderr)
        raise SystemExit(1)
    return value


def ask_opencode(question: str, context: str, api_key: str, model: str = DEFAULT_MODEL) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": f"Contexte :\n\n{context}\n\n---\n\nQuestion : {question}"},
        ],
        "temperature": 0.2,
    }
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _parse_ask_body(raw: bytes) -> tuple[str, str, str]:
    body = json.loads(raw or b"{}")
    question = str(body.get("question") or "").strip()
    context = str(body.get("context") or "")
    model = resolve_model(body.get("model"))
    return question, context, model


def _handle_ask(handler: BaseHTTPRequestHandler, api_key: str, shared_secret: str) -> None:
    if handler.path != "/ask":
        handler.send_json(404, {"error": "not found"})
        return
    if handler.headers.get("X-Relay-Secret") != shared_secret:
        handler.send_json(401, {"error": "unauthorized"})
        return
    length = int(handler.headers.get("Content-Length") or 0)
    try:
        question, context, model = _parse_ask_body(handler.rfile.read(length) if length else b"{}")
    except Exception as exc:  # noqa: BLE001 - report and move on, don't crash the server
        handler.send_json(400, {"error": f"invalid request body: {exc}"})
        return
    if not question:
        handler.send_json(400, {"error": "missing question"})
        return
    try:
        answer = ask_opencode(question, context, api_key, model)
    except Exception as exc:  # noqa: BLE001 - report upstream failure, keep serving
        print(f"[relay] OpenCode Zen call failed: {exc}", file=sys.stderr)
        handler.send_json(502, {"error": str(exc)})
        return
    print(
        f"[relay] answered with {model} ({len(question)} char question -> {len(answer)} char answer)",
        file=sys.stderr,
    )
    handler.send_json(200, {"answer": answer})


def make_handler(api_key: str, shared_secret: str) -> type:
    class RelayHandler(BaseHTTPRequestHandler):
        def send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self.send_json(200, {"status": "ok", "model": DEFAULT_MODEL})
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            _handle_ask(self, api_key, shared_secret)

        def log_message(self, fmt: str, *args: object) -> None:  # quieter default access log
            print(f"[relay] {self.address_string()} - {fmt % args}", file=sys.stderr)

    return RelayHandler


def main() -> int:
    api_key = _env_or_exit("OPENCODE_API_KEY")
    shared_secret = _env_or_exit("RELAY_SHARED_SECRET")
    server = ThreadingHTTPServer((HOST, PORT), make_handler(api_key, shared_secret))
    print(
        f"[relay] listening on http://{HOST}:{PORT} (default model={DEFAULT_MODEL}, upstream={API_URL})",
        file=sys.stderr,
    )
    print(f"[relay] expose it with: cloudflared tunnel --url http://{HOST}:{PORT}", file=sys.stderr)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
