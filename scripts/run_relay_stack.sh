#!/usr/bin/env bash
# Runs the free-model relay stack and keeps the live site pointed at it —
# meant to be a single command anyone can run (you, a friend, a spare always-on
# device) to become the current backend for /assistant/, without needing
# Cloudflare account access.
#
# What it does:
#   1. starts scripts/llm_relay.py (only needs python3 + `requests`, NOT the
#      full project .venv — this is deliberately portable to any machine)
#   2. exposes it with a Cloudflare quick tunnel (`cloudflared tunnel --url`)
#   3. watches the tunnel's log for its https://*.trycloudflare.com URL and
#      self-registers it with the already-deployed Worker by calling
#      POST <site>/api/relay/register (authenticated with RELAY_SHARED_SECRET)
#      -- see platform/site/worker/ask.ts's handleRelayRegister. Whoever
#      registers most recently becomes the active backend; no wrangler
#      login or Cloudflare permissions needed to run this script.
#
# Why this exists: platform/site/worker/ask.ts calling OpenCode Zen directly
# from Cloudflare Workers gets throttled (FreeUsageLimitError) regardless of
# API key/model -- the same key from a residential connection works fine.
# This relay makes that residential call instead. Whoever runs it becomes the
# current answering backend for the live site, for as long as this script
# and the machine it's on stay up.
#
# Requirements on whichever machine runs this: python3, `pip install requests`
# (or `pip3 install requests --break-system-packages` on newer macOS/Linux),
# and cloudflared (`brew install cloudflared` on macOS). That's it -- no need
# to clone the rest of this repo's Python environment.
#
# Meant to be run by launchd/systemd (see scripts/com.lexismollis.relay.plist
# for the macOS launchd version) so it starts automatically and restarts if
# it crashes -- "always on while this machine is on", no terminal babysitting
# once installed.
#
# Requires a local secrets file (NOT committed, lives outside the repo):
#   ~/.lexis_mollis_relay.env
#     OPENCODE_API_KEY=...        # from https://opencode.ai/zen/ -- can be
#                                 # shared with someone you trust to run this
#     RELAY_SHARED_SECRET=...     # set once as a Worker secret:
#                                 #   cd platform/site && npx wrangler secret put RELAY_SHARED_SECRET
#                                 # then given to anyone else who'll run this script
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_FILE="${LEXIS_RELAY_SECRETS_FILE:-$HOME/.lexis_mollis_relay.env}"
LOG_DIR="${LEXIS_RELAY_LOG_DIR:-$HOME/Library/Logs/lexis-mollis-relay}"
SITE_URL="${LEXIS_SITE_URL:-https://lexis-mollis.mk-74a.workers.dev}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "$LOG_DIR"

if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "[stack] Missing $SECRETS_FILE (OPENCODE_API_KEY=... / RELAY_SHARED_SECRET=...) -- see this script's header." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$SECRETS_FILE"
set +a

RELAY_PID=""
TUNNEL_PID=""
cleanup() {
  echo "[stack] stopping relay + tunnel..." >&2
  [[ -n "$RELAY_PID" ]] && kill "$RELAY_PID" 2>/dev/null || true
  [[ -n "$TUNNEL_PID" ]] && kill "$TUNNEL_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "[stack] starting relay ($PYTHON_BIN scripts/llm_relay.py)..." >&2
"$PYTHON_BIN" "$REPO_DIR/scripts/llm_relay.py" >>"$LOG_DIR/relay.log" 2>&1 &
RELAY_PID=$!

# --protocol http2 (TCP-based) instead of the default QUIC (UDP-based): some
# networks/routers/ISPs throttle or interfere with UDP, which shows up as
# repeated "control stream encountered a failure" / reconnect loops in
# tunnel.log even though the tunnel URL itself was created successfully.
# HTTP/2 is slightly higher-latency but far more reliable on those networks.
# Override with LEXIS_TUNNEL_PROTOCOL=quic to go back to the default.
TUNNEL_PROTOCOL="${LEXIS_TUNNEL_PROTOCOL:-http2}"

start_tunnel() {
  echo "[stack] starting cloudflared tunnel..." >&2
  : > "$LOG_DIR/tunnel.log"
  cloudflared tunnel --protocol "$TUNNEL_PROTOCOL" --url http://127.0.0.1:8799 >>"$LOG_DIR/tunnel.log" 2>&1 &
  TUNNEL_PID=$!
}
start_tunnel

LAST_URL=""
LAST_REGISTER_EPOCH=0
# Must be well under the Worker's RELAY_STALE_MS (10 minutes, ask.ts) so a
# still-healthy relay never gets treated as offline just because its tunnel
# URL hasn't changed -- registration is otherwise a one-time event per URL,
# and a stable tunnel keeps the same URL indefinitely.
HEARTBEAT_INTERVAL_SECONDS="${LEXIS_RELAY_HEARTBEAT_SECONDS:-240}"
while kill -0 "$RELAY_PID" 2>/dev/null; do
  # A cloudflared quick tunnel can outlive its own DNS registration -- e.g.
  # after the machine sleeps or switches networks (wifi at the office ->
  # wifi at home), Cloudflare's edge stops recognizing the tunnel ID but the
  # cloudflared *process* itself doesn't crash: it just retries the same
  # dead tunnel forever ("Unauthorized: Tunnel not found" in tunnel.log), so
  # a plain `kill -0 $TUNNEL_PID` health check never notices anything is
  # wrong. Detect that error string specifically and force a hard restart of
  # just the tunnel (new process -> brand new *.trycloudflare.com URL),
  # rather than waiting for something that will never happen on its own.
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "[stack] tunnel process died -- restarting it..." >&2
    start_tunnel
  elif tail -n 5 "$LOG_DIR/tunnel.log" 2>/dev/null | grep -q "Unauthorized: Tunnel not found"; then
    echo "[stack] tunnel is stuck retrying a dead registration -- forcing restart for a fresh URL..." >&2
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    LAST_URL=""
    start_tunnel
    sleep 3
  fi

  URL=$(grep -Eo 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$LOG_DIR/tunnel.log" 2>/dev/null | tail -1 || true)
  NOW_EPOCH=$(date +%s)
  if [[ -n "$URL" ]] && { [[ "$URL" != "$LAST_URL" ]] || (( NOW_EPOCH - LAST_REGISTER_EPOCH >= HEARTBEAT_INTERVAL_SECONDS )); }; then
    echo "[stack] tunnel URL: $URL -- registering with $SITE_URL" >&2
    HTTP_STATUS=$(curl -s -o "$LOG_DIR/register_response.json" -w '%{http_code}' \
      -X POST "$SITE_URL/api/relay/register" \
      -H "X-Relay-Secret: $RELAY_SHARED_SECRET" \
      -H "Content-Type: application/json" \
      -d "{\"url\": \"$URL/ask\"}" 2>>"$LOG_DIR/register.log" || echo "curl_failed")
    if [[ "$HTTP_STATUS" == "200" ]]; then
      LAST_URL="$URL"
      LAST_REGISTER_EPOCH=$NOW_EPOCH
      echo "[stack] registered successfully as the active relay." >&2
    else
      echo "[stack] registration failed (HTTP $HTTP_STATUS) -- see $LOG_DIR/register_response.json and $LOG_DIR/register.log" >&2
    fi
  fi
  sleep 5
done

echo "[stack] relay process exited -- see logs in $LOG_DIR" >&2
exit 1
