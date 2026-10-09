#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
DEPLOY_STATE_DIR="${DEPLOY_ROOT}/data/deployment"
DEPLOY_PROJECT_OVERRIDE=""
DEPLOY_CONFIGURE_ARGS=()
DEPLOY_INSTALL_DOCKER=false
DEPLOY_NO_START=false
DEPLOY_DOCKER_SUDO=false
DEPLOY_DOCKER_COMMAND=(docker)

deploy_fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

deploy_help() {
    printf '%s\n' \
        'Usage: scripts/deploy/<install|start|stop|status>.sh [--state-dir PATH]' \
        'All entrypoints: --docker-sudo (explicit Linux sudo access to Docker)' \
        'Install options: --install-docker --no-start --project-name NAME' \
        'Configure options: --public-url URL --owner-username NAME --enable-bot' \
        '  --bind-address ADDRESS --http-port PORT --https-port PORT' \
        '  --worker-count N --worker-concurrency N --scheduler-interval N --start-timeout N' \
        '  --network-subnet CIDR --run-uid UID --run-gid GID' \
        'Secrets are entered interactively; do not put passwords or bot tokens in arguments.'
}

deploy_parse_args() {
    local operation="$1"
    shift
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --docker-sudo)
                DEPLOY_DOCKER_SUDO=true
                DEPLOY_DOCKER_COMMAND=(sudo docker)
                shift
                ;;
            --state-dir)
                [ "$#" -ge 2 ] || deploy_fail '--state-dir requires a path.'
                DEPLOY_STATE_DIR="$2"
                shift 2
                ;;
            --project-name)
                [ "$operation" = install ] || deploy_fail '--project-name belongs to installation.'
                [ "$#" -ge 2 ] || deploy_fail '--project-name requires a name.'
                DEPLOY_PROJECT_OVERRIDE="$2"
                shift 2
                ;;
            --install-docker)
                [ "$operation" = install ] || deploy_fail '--install-docker belongs to installation.'
                DEPLOY_INSTALL_DOCKER=true
                shift
                ;;
            --no-start)
                [ "$operation" = install ] || deploy_fail '--no-start belongs to installation.'
                DEPLOY_NO_START=true
                shift
                ;;
            --enable-bot)
                [ "$operation" = install ] || deploy_fail '--enable-bot belongs to installation.'
                DEPLOY_CONFIGURE_ARGS+=("$1")
                shift
                ;;
            --public-url|--owner-username|--bind-address|--http-port|--https-port|--worker-count|--worker-concurrency|--scheduler-interval|--start-timeout|--network-subnet|--run-uid|--run-gid)
                [ "$operation" = install ] || deploy_fail 'Configuration options belong to installation.'
                [ "$#" -ge 2 ] || deploy_fail "$1 requires a value."
                DEPLOY_CONFIGURE_ARGS+=("$1" "$2")
                shift 2
                ;;
            --help|-h)
                deploy_help
                exit 0
                ;;
            *) deploy_fail "Unknown argument: $1" ;;
        esac
    done
    [ -n "$DEPLOY_STATE_DIR" ] || deploy_fail 'State directory cannot be empty.'
    case "$DEPLOY_STATE_DIR" in
        /*) ;;
        *) DEPLOY_STATE_DIR="${PWD}/${DEPLOY_STATE_DIR}" ;;
    esac
    if [ "$operation" = install ]; then
        mkdir -p "$DEPLOY_STATE_DIR"
    fi
    [ -d "$DEPLOY_STATE_DIR" ] || deploy_fail 'State directory is missing; run install.sh first.'
    DEPLOY_STATE_DIR="$(cd "$DEPLOY_STATE_DIR" && pwd -P)"
}

deploy_docker() {
    "${DEPLOY_DOCKER_COMMAND[@]}" "$@"
}

deploy_install_docker() {
    local platform release installer result
    platform="$(uname -s)"
    case "$platform" in
        Linux)
            if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
                deploy_fail 'On Windows/WSL, install Docker Desktop and enable integration for this WSL distribution: https://docs.docker.com/desktop/features/wsl/'
            fi
            [ -r /etc/os-release ] || deploy_fail 'Unknown Linux distribution; install Docker manually: https://docs.docker.com/engine/install/'
            release="$(sed -n 's/^ID=//p' /etc/os-release)"
            release="${release#\"}"
            release="${release%\"}"
            case "$release" in
                ubuntu|debian|raspbian|fedora|centos|rhel) ;;
                *) deploy_fail 'This distribution needs its documented Docker installation: https://docs.docker.com/engine/install/' ;;
            esac
            command -v curl >/dev/null 2>&1 || deploy_fail 'Install curl first or follow https://docs.docker.com/engine/install/'
            installer="$(mktemp "${TMPDIR:-/tmp}/papilio-docker-install.XXXXXX")"
            if ! curl --fail --silent --show-error --location https://get.docker.com --output "$installer"; then
                rm -f "$installer"
                deploy_fail 'Downloading the official Docker installation script failed.'
            fi
            result=0
            if [ "$(id -u)" -eq 0 ]; then
                sh "$installer" || result=$?
            elif command -v sudo >/dev/null 2>&1; then
                sudo sh "$installer" || result=$?
            else
                rm -f "$installer"
                deploy_fail 'Docker installation needs administrator access; install it using the official instructions.'
            fi
            rm -f "$installer"
            [ "$result" -eq 0 ] || deploy_fail 'Official Docker installation failed; application volumes were not changed.'
            ;;
        Darwin)
            command -v brew >/dev/null 2>&1 || deploy_fail 'Install Docker Desktop: https://docs.docker.com/desktop/setup/install/mac-install/'
            brew install --cask docker
            open -a Docker
            printf '%s\n' 'Finish Docker Desktop setup, wait for its engine, then run install.sh again.'
            ;;
        *) deploy_fail 'Use Docker Desktop with WSL2 on Windows: https://docs.docker.com/desktop/features/wsl/' ;;
    esac
}

deploy_check_docker() {
    local engine help
    case "$(uname -s)" in
        Linux|Darwin) ;;
        *) deploy_fail 'Run these Bash scripts in WSL2 on Windows: https://docs.docker.com/desktop/features/wsl/' ;;
    esac
    if [ "$DEPLOY_DOCKER_SUDO" = true ]; then
        [ "$(uname -s)" = Linux ] || deploy_fail '--docker-sudo is supported on Linux only.'
        command -v sudo >/dev/null 2>&1 || deploy_fail '--docker-sudo requires sudo to be installed.'
    fi
    if ! command -v docker >/dev/null 2>&1; then
        if [ "$DEPLOY_INSTALL_DOCKER" = true ]; then
            deploy_install_docker
        else
            deploy_fail 'Docker is required: https://docs.docker.com/get-started/get-docker/ . Install it or explicitly use install.sh --install-docker.'
        fi
    fi
    command -v docker >/dev/null 2>&1 || deploy_fail 'Docker installation has not made the docker command available.'
    deploy_docker compose version >/dev/null 2>&1 || deploy_fail 'Docker Compose v2 is required: https://docs.docker.com/compose/install/'
    engine="$(deploy_docker info --format '{{.OSType}}' 2>/dev/null)" || deploy_fail 'Docker engine is unavailable. Start Docker Desktop/Engine and ensure this user can access it, or explicitly use --docker-sudo on Linux.'
    [ "$engine" = linux ] || deploy_fail 'Select the Linux-container Docker engine.'
    help="$(deploy_docker compose up --help)"
    [[ "$help" = *'--wait-timeout'* ]] || deploy_fail 'Update Docker Compose to a release supporting up --wait-timeout.'
}

# Read only these nonsecret fields. Never execute compose.env as shell code.
deploy_read_setting() {
    local name="$1" key value result="" found=false
    case "$name" in PROJECT_NAME|PUBLIC_URL|BOT_ENABLED|START_TIMEOUT|PYTHON_IMAGE) ;; *) deploy_fail 'Unsupported compose setting.' ;; esac
    while IFS='=' read -r key value || [ -n "$key" ]; do
        if [ "$key" = "$name" ]; then
            [ "$found" = false ] || deploy_fail "Duplicate $name in compose.env."
            found=true
            result="${value%$'\r'}"
        fi
    done < "${DEPLOY_STATE_DIR}/compose.env"
    if [[ "$result" = \"*\" ]]; then
        result="${result#\"}"
        result="${result%\"}"
    elif [[ "$result" = \'*\' ]]; then
        result="${result#\'}"
        result="${result%\'}"
    fi
    printf '%s' "$result"
}

deploy_load_state() {
    [ -f "${DEPLOY_STATE_DIR}/compose.env" ] || deploy_fail 'compose.env is missing; run install.sh first.'
    [ -f "${DEPLOY_ROOT}/deployment/compose.yml" ] || deploy_fail 'Deployment compose file is missing.'
    DEPLOY_PROJECT_NAME="$(deploy_read_setting PROJECT_NAME)"
    [[ "$DEPLOY_PROJECT_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || deploy_fail 'Invalid saved project name.'
    DEPLOY_BOT_ENABLED="$(deploy_read_setting BOT_ENABLED)"
    case "$DEPLOY_BOT_ENABLED" in true|false) ;; *) deploy_fail 'Invalid saved bot state.' ;; esac
    DEPLOY_START_TIMEOUT="$(deploy_read_setting START_TIMEOUT)"
    [[ "$DEPLOY_START_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || deploy_fail 'Invalid saved start timeout.'
    deploy_verify_ownership
}

deploy_verify_ownership() {
    local kind resources resource actual format
    for kind in container volume network; do
        case "$kind" in
            container)
                resources="$(deploy_docker ps --all --quiet --filter "label=com.docker.compose.project=${DEPLOY_PROJECT_NAME}")" || deploy_fail 'Cannot list project containers; no lifecycle changes were made.'
                format='{{ index .Config.Labels "io.papilio-proxy.state" }}'
                ;;
            volume)
                resources="$(deploy_docker volume ls --quiet --filter "label=com.docker.compose.project=${DEPLOY_PROJECT_NAME}")" || deploy_fail 'Cannot list project volumes; no lifecycle changes were made.'
                format='{{ index .Labels "io.papilio-proxy.state" }}'
                ;;
            network)
                resources="$(deploy_docker network ls --quiet --filter "label=com.docker.compose.project=${DEPLOY_PROJECT_NAME}")" || deploy_fail 'Cannot list project networks; no lifecycle changes were made.'
                format='{{ index .Labels "io.papilio-proxy.state" }}'
                ;;
        esac
        while IFS= read -r resource || [ -n "$resource" ]; do
            [ -n "$resource" ] || continue
            actual="$(deploy_docker "$kind" inspect --format "$format" "$resource")" || deploy_fail "Cannot verify $kind ownership; no lifecycle changes were made."
            [ "$actual" = "$DEPLOY_STATE_DIR" ] || deploy_fail "Project $kind ownership does not match this state directory. Choose a different project name; no lifecycle changes were made."
        done <<< "$resources"
    done
}

deploy_compose() {
    local origin
    local files=(--file "${DEPLOY_ROOT}/deployment/compose.yml")
    origin="$(deploy_read_setting PUBLIC_URL)"
    if [[ "$origin" = https://* ]]; then
        files+=(--file "${DEPLOY_ROOT}/deployment/compose.https.yml")
    fi
    (
        # Persisted installation settings own these values, not ambient shells.
        unset STATE_DIR PUBLIC_URL OWNER_USERNAME BOT_ENABLED BIND_ADDRESS \
            HTTP_PORT HTTPS_PORT WORKER_COUNT WORKER_CONCURRENCY \
            SCHEDULER_INTERVAL START_TIMEOUT RUN_UID RUN_GID NETWORK_SUBNET \
            CADDY_IPV4 PROJECT_NAME PUBLIC_HOST PYTHON_IMAGE NODE_IMAGE \
            CADDY_IMAGE MYSQL_IMAGE REDIS_IMAGE COMPOSE_PROFILES
        deploy_docker compose --env-file "${DEPLOY_STATE_DIR}/compose.env" \
            --project-name "$DEPLOY_PROJECT_NAME" "${files[@]}" "$@"
    )
}

deploy_show_url() {
    local url
    url="$(deploy_read_setting PUBLIC_URL)"
    if [[ "$url" = *'@'* || "$url" = *$'\n'* ]]; then
        deploy_fail 'Saved public URL must not contain credentials or newlines.'
    fi
    printf 'Panel: %s\n' "$url"
    if [ "$DEPLOY_BOT_ENABLED" = false ]; then
        printf '%s\n' 'Telegram bot: disabled.'
    fi
}

deploy_failure_notice() {
    printf '%s\n' \
        'Deployment command failed. Existing volumes and configuration are preserved.' \
        'Inspect scripts/deploy/status.sh and the failing service logs before retrying.' >&2
}
