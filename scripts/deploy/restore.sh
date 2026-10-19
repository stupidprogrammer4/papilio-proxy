#!/usr/bin/env bash

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
trap deploy_failure_notice ERR
deploy_parse_args restore "$@"

resolve_existing_file() {
    local requested="$1" description="$2" directory filename
    [ -f "$requested" ] && [ ! -L "$requested" ] \
        || deploy_fail "$description must be a regular, non-symlink file."
    directory="$(cd "$(dirname "$requested")" && pwd -P)" \
        || deploy_fail "$description directory is unavailable."
    filename="$(basename "$requested")"
    [[ "$filename" != . && "$filename" != .. ]] \
        || deploy_fail "$description path is invalid."
    printf '%s/%s' "$directory" "$filename"
}

key_file="$(resolve_existing_file "$DEPLOY_RECOVERY_KEY_FILE" 'Recovery key')"
archive="$(resolve_existing_file "$DEPLOY_ARCHIVE_FILE" 'Backup archive')"
permissions=""
if permissions="$(stat -c '%a' "$key_file" 2>/dev/null)"; then
    :
elif permissions="$(stat -f '%Lp' "$key_file" 2>/dev/null)"; then
    :
else
    deploy_fail 'Cannot verify recovery key permissions.'
fi
case "$permissions" in
    400|600) ;;
    *) deploy_fail 'Recovery key must be readable only by its owner (mode 0400 or 0600).' ;;
esac

archive_directory="$(dirname "$archive")"
archive_name="$(basename "$archive")"
recovery_config="/opt/deployment/recovery.yml"
recovery_key="/run/papilio-recovery.key"
container_archive="/backup/${archive_name}"

deploy_check_docker
deploy_load_state

# Reject an unreadable or damaged archive before stopping any application service.
deploy_compose run --rm --no-deps \
    --volume "${key_file}:${recovery_key}:ro" \
    --volume "${archive_directory}:/backup:ro" \
    api python /app/scripts/recovery.py \
    --recovery-config "$recovery_config" \
    --key-file "$recovery_key" \
    verify --archive "$container_archive"

# Quiesce every application writer, including the durable event consumer.
deploy_compose stop api events-worker worker scheduler web
if [ "$DEPLOY_BOT_ENABLED" = true ]; then
    deploy_compose --profile bot stop bot
fi
deploy_compose up --detach --no-build --wait --wait-timeout "$DEPLOY_START_TIMEOUT" mysql

# The native recovery command only restores into an empty database and never drops data.
deploy_compose run --rm --no-deps \
    --volume "${key_file}:${recovery_key}:ro" \
    --volume "${archive_directory}:/backup:ro" \
    api python /app/scripts/recovery.py \
    --recovery-config "$recovery_config" \
    --key-file "$recovery_key" \
    restore --archive "$container_archive" --target-config /app/config.yml

start_args=("${DEPLOY_ROOT}/scripts/deploy/start.sh" --state-dir "$DEPLOY_STATE_DIR")
if [ "$DEPLOY_DOCKER_SUDO" = true ]; then
    start_args+=(--docker-sudo)
fi
bash "${start_args[@]}"

printf 'Verified backup restored into the configured deployment: %s\n' "$archive"
