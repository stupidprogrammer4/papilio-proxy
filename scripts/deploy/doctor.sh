#!/usr/bin/env bash

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
trap deploy_failure_notice ERR
deploy_parse_args doctor "$@"
deploy_check_docker
deploy_load_state

rows="$(deploy_compose --profile bot ps --all --format '{{.Service}};{{.State}};{{.Health}}')"
failed=false

report_service() {
    local label="$1" service="$2" require_health="$3" optional="$4"
    local row state health result
    if [ "$optional" = true ]; then
        printf '%s: disabled\n' "$label"
        return
    fi
    row="$(printf '%s\n' "$rows" | awk -F';' -v name="$service" '$1 == name { value=$0 } END { print value }')"
    state="${row#*;}"
    if [ "$state" = "$row" ]; then
        printf '%s: unavailable (container missing)\n' "$label"
        failed=true
        return
    fi
    health="${state#*;}"
    state="${state%%;*}"
    result="$state"
    if [ "$state" = running ] && [ "$require_health" = true ]; then
        if [ "$health" = healthy ]; then
            result=healthy
        else
            result="${health:-unavailable (healthcheck missing)}"
            failed=true
        fi
    elif [ "$state" != running ]; then
        result="unavailable ($state)"
        failed=true
    else
        result='running (no healthcheck)'
    fi
    printf '%s: %s\n' "$label" "$result"
}

printf '%s\n' 'Papilio deployment preflight'
report_service API api true false
report_service MySQL mysql true false
report_service Redis redis true false
report_service NATS nats true false
report_service 'Events worker' events-worker true false
report_service Worker worker false false
report_service Scheduler scheduler false false
report_service Web web true false
if [ "$DEPLOY_BOT_ENABLED" = true ]; then
    report_service 'Telegram bot' bot true false
else
    report_service 'Telegram bot' bot true true
fi
printf '%s\n' \
    'OCR provider: not checked by this command (external integration)' \
    'Node runtime: not checked by this command (separate enrollment)' \
    'Payment source: not checked by this command (external integration)'

if [ "$failed" = true ]; then
    printf '%s\n' 'Deployment preflight failed; inspect the named service with status.sh and Docker logs.' >&2
    exit 1
fi
printf '%s\n' 'Compose healthchecks passed. Worker execution and scheduler dispatch were not exercised.'
