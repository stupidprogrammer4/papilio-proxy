#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

readonly REPOSITORY="stupidprogrammer4/papilio-proxy"
readonly ARCHIVE_BASE="https://codeload.github.com/${REPOSITORY}/tar.gz"
ref="main"
public_url=""
owner_username=""
state_dir=""
bind_address=""
http_port=""
https_port=""
forwarded=()

usage() {
    cat <<'EOF'
Install Papilio on a Linux server with one command.

Usage:
  set -o pipefail; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/main/scripts/deploy/quick-install.sh | bash -s -- --public-url https://panel.example.com --owner-username admin

Required:
  --public-url URL       Public HTTPS domain (or local http://127.0.0.1:8080)
  --owner-username NAME  Initial panel administrator

Optional:
  --enable-bot           Also configure Telegram; asks for its token privately
  --state-dir PATH       Persistent configuration (default: ~/papilio-state)
  --ref NAME             Git branch/tag to install (default: main)
  --bind-address IPv4    Public HTTPS defaults to 0.0.0.0
  --http-port PORT       Public HTTPS defaults to 80; local mode defaults to 8080
  --https-port PORT      Public HTTPS defaults to 443
  --help                 Show this help

The installer may install Docker on supported Linux distributions. It asks for
the owner password in a private terminal. Application cores remain disabled.
EOF
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h)
            usage
            exit 0
            ;;
        --ref)
            [ "$#" -ge 2 ] || fail '--ref requires a branch or tag name.'
            ref="$2"
            shift 2
            ;;
        --public-url)
            [ "$#" -ge 2 ] || fail '--public-url requires a value.'
            public_url="$2"
            forwarded+=("$1" "$2")
            shift 2
            ;;
        --owner-username)
            [ "$#" -ge 2 ] || fail '--owner-username requires a value.'
            owner_username="$2"
            forwarded+=("$1" "$2")
            shift 2
            ;;
        --state-dir)
            [ "$#" -ge 2 ] || fail '--state-dir requires a path.'
            state_dir="$2"
            shift 2
            ;;
        --bind-address)
            [ "$#" -ge 2 ] || fail '--bind-address requires an address.'
            bind_address="$2"
            forwarded+=("$1" "$2")
            shift 2
            ;;
        --http-port)
            [ "$#" -ge 2 ] || fail '--http-port requires a port.'
            http_port="$2"
            forwarded+=("$1" "$2")
            shift 2
            ;;
        --https-port)
            [ "$#" -ge 2 ] || fail '--https-port requires a port.'
            https_port="$2"
            forwarded+=("$1" "$2")
            shift 2
            ;;
        --enable-bot|--no-start|--docker-sudo|--install-docker)
            forwarded+=("$1")
            shift
            ;;
        --project-name|--network-subnet|--worker-count|--worker-concurrency|--scheduler-interval|--start-timeout|--run-uid|--run-gid)
            [ "$#" -ge 2 ] || fail "$1 requires a value."
            forwarded+=("$1" "$2")
            shift 2
            ;;
        *) fail "Unknown option: $1 (use --help)." ;;
    esac
done

[ -n "$public_url" ] || fail 'Set --public-url to your domain or local address.'
[ -n "$owner_username" ] || fail 'Set --owner-username for the panel administrator.'
[[ "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || fail 'Invalid branch or tag name.'
[[ "$public_url" != *$'\n'* && "$public_url" != *'@'* ]] || fail 'URL cannot contain credentials or newlines.'
[ -r /dev/tty ] || fail 'Run this command from an interactive terminal so secrets can be entered privately.'
[ "$(uname -s)" = Linux ] || fail 'The one-line server installer currently supports Linux. Use Docker Desktop for macOS/WSL and run install.sh from the checkout.'
if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
    fail 'For WSL, enable Docker Desktop integration and run install.sh from the checkout.'
fi

case "$public_url" in
    https://*)
        [[ "$public_url" =~ ^https://([A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?)(:([0-9]{1,5}))?$ ]] \
            || fail 'Use a DNS hostname without a path, query, fragment or credentials.'
        url_https_port="${BASH_REMATCH[4]:-443}"
        if [ -n "$https_port" ] && [ "$https_port" != "$url_https_port" ]; then
            fail 'The HTTPS URL port and --https-port must match.'
        fi
        [ -n "$bind_address" ] || forwarded+=(--bind-address 0.0.0.0)
        [ -n "$http_port" ] || forwarded+=(--http-port 80)
        [ -n "$https_port" ] || forwarded+=(--https-port "$url_https_port")
        ;;
    http://127.0.0.1:*|http://localhost:*)
        [[ "$public_url" =~ ^http://(127\.0\.0\.1|localhost):([0-9]{1,5})$ ]] \
            || fail 'Local HTTP URL must be localhost with an explicit port.'
        url_http_port="${BASH_REMATCH[2]}"
        if [ -n "$http_port" ] && [ "$http_port" != "$url_http_port" ]; then
            fail 'The local URL port and --http-port must match.'
        fi
        [ -n "$bind_address" ] || forwarded+=(--bind-address 127.0.0.1)
        [ -n "$http_port" ] || forwarded+=(--http-port "$url_http_port")
        ;;
    *) fail 'Use HTTPS for a public domain. Plain HTTP is supported only for local testing.' ;;
esac

command -v curl >/dev/null 2>&1 || fail 'Install curl and retry.'
command -v tar >/dev/null 2>&1 || fail 'Install tar and retry.'
command -v flock >/dev/null 2>&1 || fail 'Install util-linux (flock) and retry.'
[ -n "${HOME:-}" ] || fail 'HOME is not set; run the installer as the deployment user.'

install_home="${PAPILIO_INSTALL_HOME:-${HOME}/.local/share/papilio-proxy}"
source_dir="${install_home}/source"
mkdir -p "$install_home"
chmod 700 "$install_home"
exec 9>"${install_home}/install.lock"
flock -n 9 || fail 'Another Papilio installation is already running.'

if [ -z "$state_dir" ]; then
    state_dir="${PAPILIO_STATE_DIR:-${HOME}/papilio-state}"
fi

temporary="$(mktemp -d "${install_home}/.quick-install.XXXXXX")"
backup="${install_home}/.source-backup.$$"
finished=false

cleanup() {
    local status=$?
    if [ "$finished" = false ]; then
        if [ -d "$backup" ]; then
            rm -rf -- "$source_dir"
            mv -- "$backup" "$source_dir"
        fi
    elif [ -d "$backup" ]; then
        rm -rf -- "$backup"
    fi
    rm -rf -- "$temporary"
    exit "$status"
}
trap cleanup EXIT

archive="${temporary}/source.tar.gz"
extracted="${temporary}/source"
mkdir -m 700 "$extracted"
printf 'Downloading Papilio (%s)…\n' "$ref"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    --max-filesize 250000000 \
    "${ARCHIVE_BASE}/${ref}" --output "$archive"
tar -tzf "$archive" > "${temporary}/archive.list" || fail 'Downloaded source archive is invalid.'
while IFS= read -r member; do
    case "$member" in
    /*|../*|*/../*|*/..|papilio-proxy-*) ;;
        *) fail 'Source archive contains an unexpected path.' ;;
    esac
done < "${temporary}/archive.list"
tar -xzf "$archive" --strip-components=1 -C "$extracted"
[ -f "${extracted}/scripts/deploy/install.sh" ] || fail 'Source archive is missing the installer.'
[ -f "${extracted}/deployment/compose.yml" ] || fail 'Source archive is missing deployment files.'
printf '%s\n' "$ref" > "${extracted}/.papilio-quick-install-ref"

if [ -e "$source_dir" ] || [ -L "$source_dir" ]; then
    [ -d "$source_dir" ] && [ ! -L "$source_dir" ] \
        || fail 'Existing source path is not a regular directory; no files were changed.'
    [ -f "${source_dir}/.papilio-quick-install-ref" ] \
        || fail 'Existing source was not created by this installer; choose another PAPILIO_INSTALL_HOME.'
    mv -- "$source_dir" "$backup"
fi
mv -- "$extracted" "$source_dir"

install_args=(--state-dir "$state_dir" "${forwarded[@]}")
if ! command -v docker >/dev/null 2>&1; then
    install_args+=(--install-docker)
    if [ "$(id -u)" -ne 0 ]; then
        command -v sudo >/dev/null 2>&1 || fail 'Docker setup requires root or sudo.'
        install_args+=(--docker-sudo)
    fi
elif ! docker info >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ] || ! command -v sudo >/dev/null 2>&1; then
        fail 'Docker is installed but its engine is unavailable to this user.'
    fi
    install_args+=(--docker-sudo)
fi

printf 'Installing from %s\nPersistent files: %s\n' "$source_dir" "$state_dir"
"${source_dir}/scripts/deploy/install.sh" "${install_args[@]}" </dev/tty
finished=true
if [ -d "$backup" ]; then
    rm -rf -- "$backup"
fi
printf '\nInstallation finished. Source and lifecycle scripts: %s\n' "$source_dir"
printf 'Private configuration and database state: %s\n' "$state_dir"
