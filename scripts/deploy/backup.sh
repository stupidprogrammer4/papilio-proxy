#!/usr/bin/env bash

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
trap deploy_failure_notice ERR
deploy_parse_args backup "$@"

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

resolve_output_path() {
    local requested="$1" directory filename
    [ -n "$requested" ] || deploy_fail 'Backup output path is required.'
    if [[ "$requested" != /* ]]; then
        requested="${PWD}/${requested}"
    fi
    directory="$(cd "$(dirname "$requested")" && pwd -P)" \
        || deploy_fail 'Backup output directory must already exist.'
    filename="$(basename "$requested")"
    [[ "$filename" != . && "$filename" != .. ]] \
        || deploy_fail 'Backup output filename is invalid.'
    [ ! -e "${directory}/${filename}" ] && [ ! -L "${directory}/${filename}" ] \
        || deploy_fail 'Backup output already exists; choose a new filename.'
    [ -w "$directory" ] || deploy_fail 'Backup output directory is not writable.'
    printf '%s/%s' "$directory" "$filename"
}

key_file="$(resolve_existing_file "$DEPLOY_RECOVERY_KEY_FILE" 'Recovery key')"
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

output="$(resolve_output_path "$DEPLOY_BACKUP_OUTPUT")"
output_directory="$(dirname "$output")"
output_name="$(basename "$output")"
recovery_config="/opt/deployment/recovery.yml"
recovery_key="/run/papilio-recovery.key"

deploy_check_docker
deploy_load_state

deploy_compose run --rm --no-deps \
    --volume "${key_file}:${recovery_key}:ro" \
    --volume "${output_directory}:/backup" \
    api python /app/scripts/recovery.py \
    --recovery-config "$recovery_config" \
    --key-file "$recovery_key" \
    create --app-config /app/config.yml --output "/backup/${output_name}"

deploy_compose run --rm --no-deps \
    --volume "${key_file}:${recovery_key}:ro" \
    --volume "${output_directory}:/backup" \
    api python /app/scripts/recovery.py \
    --recovery-config "$recovery_config" \
    --key-file "$recovery_key" \
    verify --archive "/backup/${output_name}"

printf 'Encrypted database backup created and verified: %s\n' "$output"
printf '%s\n' 'Keep the recovery key separately from this archive.'
