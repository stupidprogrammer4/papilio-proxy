#!/usr/bin/env bash

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
trap deploy_failure_notice ERR
deploy_parse_args start "$@"
deploy_check_docker
deploy_load_state

# Writers stop before migration; failure retains the database for recovery.
deploy_compose --profile bot stop api worker scheduler bot
deploy_compose up --detach --no-build --wait --wait-timeout "$DEPLOY_START_TIMEOUT" mysql redis
deploy_compose --profile tools run --rm bootstrap
if [ "$DEPLOY_BOT_ENABLED" = true ]; then
    deploy_compose --profile bot up --detach --no-build --wait --wait-timeout "$DEPLOY_START_TIMEOUT" api worker scheduler web bot
else
    deploy_compose up --detach --no-build --wait --wait-timeout "$DEPLOY_START_TIMEOUT" api worker scheduler web
fi
deploy_compose exec --no-TTY api python /opt/deployment/check_gateway.py \
    "$(deploy_read_setting PUBLIC_URL)" --timeout "$DEPLOY_START_TIMEOUT"
deploy_show_url
printf '%s\n' 'Configured services started; proxy cores remain disabled.'
