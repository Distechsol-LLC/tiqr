#!/bin/sh
# Probes the TiQR server's /api/health. Each failed probe exits non-zero, so systemctl --failed
# shows it; once FAILURES_BEFORE_ALERT probes fail in a row, a critical journal entry is logged
# for the customer's monitoring to pick up. The count lives in the unit's StateDirectory.
set -eu

FAILURES_BEFORE_ALERT=3
state="${STATE_DIRECTORY:-/var/lib/tiqr-health}/failures"

# Probe the address the server binds to; a wildcard bind answers on loopback.
host="${TIQR_HOST:-127.0.0.1}"
case "$host" in
  0.0.0.0) host=127.0.0.1 ;;
  ::) host='[::1]' ;;
  *:*) host="[$host]" ;;
esac
scheme=http
insecure=
if [ -n "${TIQR_TLS_CERT:-}" ]; then
  # A self-signed certificate is fine here: the check proves the server is up, not who it is.
  scheme=https
  insecure=-k
fi
url="$scheme://$host:${TIQR_PORT:-7102}/api/health"

previous=$(cat "$state" 2>/dev/null || echo 0)
# shellcheck disable=SC2086 # $insecure is either empty or one option; it must not be quoted.
if curl -fsS $insecure --max-time 10 -o /dev/null "$url"; then
  if [ "$previous" -ge "$FAILURES_BEFORE_ALERT" ]; then
    logger -p daemon.notice -t tiqr-health "TiQR answers again at $url after $previous failed checks"
  fi
  echo 0 > "$state"
  exit 0
fi

count=$((previous + 1))
echo "$count" > "$state"
if [ "$count" -eq "$FAILURES_BEFORE_ALERT" ]; then
  logger -p daemon.crit -t tiqr-health "TiQR health check failed $count times in a row: $url"
fi
exit 1
