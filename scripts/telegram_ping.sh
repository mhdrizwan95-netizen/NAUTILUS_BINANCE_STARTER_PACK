#!/usr/bin/env bash
set -euo pipefail

# Send a Telegram message using env vars TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
# Falls back to a DNS-override if local resolver is broken.

DEFAULT_MSG="Telegram wired ✅"
MESSAGE="${*:-$DEFAULT_MSG}"

# Try to read specific vars from .env if not exported
read_env_var() {
  local name="$1"
  [ -f .env ] || return 1
  # Grep the last assignment for the var, ignore comments, trim quotes
  local line
  line=$(grep -E "^[[:space:]]*${name}=" .env | tail -n1 || true)
  [ -n "${line}" ] || return 1
  local value
  value=${line#*=}
  # strip surrounding single or double quotes if present
  value=${value%$'\r'}
  value=$(sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//" <<<"${value}")
  printf '%s' "${value}"
}

TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-$(read_env_var TELEGRAM_BOT_TOKEN || true)}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:-$(read_env_var TELEGRAM_CHAT_ID || true)}
TELEGRAM_FORCE_IPV4=${TELEGRAM_FORCE_IPV4:-$(read_env_var TELEGRAM_FORCE_IPV4 || true)}

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (env or .env)" >&2
  exit 1
fi

CURL_IP_OPT=()
if [[ "${TELEGRAM_FORCE_IPV4:-}" =~ ^([Tt]rue|1|yes)$ ]]; then
  CURL_IP_OPT=(-4)
fi

send_standard() {
  curl -sS "${CURL_IP_OPT[@]}" -m 15 \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${MESSAGE}"
}

send_with_resolve() {
  # Resolve via public DNS, bypassing local resolver
  local ip
  ip=$(nslookup api.telegram.org 1.1.1.1 2>/dev/null | awk '/^Address: / && $2 !~ /#/{print $2; exit}')
  if [ -z "${ip}" ]; then
    echo "error: failed to obtain api.telegram.org IP from 1.1.1.1" >&2
    return 1
  fi
  echo "⚠️  Local DNS failed. Using --resolve api.telegram.org:443:${ip}" >&2
  curl -sS -m 15 --resolve api.telegram.org:443:"${ip}" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${MESSAGE} (DNS fallback)"
}

# Try normal path first; if DNS error (exit 6), fallback to --resolve
set +e
resp=$(send_standard)
status=$?
set -e

if [ $status -eq 0 ]; then
  printf '%s\n' "$resp"
  exit 0
fi

if [ $status -eq 6 ]; then
  # Could not resolve host
  send_with_resolve
  exit $?
fi

echo "error: curl failed (exit $status)." >&2
exit $status

