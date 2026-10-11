#!/bin/sh
set -eu
umask 077

: "${PAPILIO_CADDYFILE_BASE64:?Missing private Caddy configuration}"
: "${PAPILIO_CADDYFILE_SHA256:?Missing Caddy configuration digest}"
if ! printf '%s' "$PAPILIO_CADDYFILE_SHA256" | grep -Eq '^[a-f0-9]{64}$'; then
    printf '%s\n' 'Invalid Caddy configuration digest' >&2
    exit 1
fi

destination=/config/papilio-Caddyfile
if [ -d "$destination" ]; then
    printf '%s\n' 'Unsafe Caddy configuration destination' >&2
    exit 1
fi
temporary=$(mktemp /config/.papilio-Caddyfile.XXXXXX)
trap 'rm -f "$temporary"' EXIT HUP INT TERM
printf '%s' "$PAPILIO_CADDYFILE_BASE64" | base64 -d > "$temporary"
actual=$(sha256sum "$temporary")
actual=${actual%% *}
if [ "$actual" != "$PAPILIO_CADDYFILE_SHA256" ]; then
    printf '%s\n' 'Caddy configuration digest mismatch' >&2
    exit 1
fi
mv -f "$temporary" "$destination"
trap - EXIT HUP INT TERM
unset PAPILIO_CADDYFILE_BASE64 PAPILIO_CADDYFILE_SHA256
exec caddy run --config "$destination" --adapter caddyfile
