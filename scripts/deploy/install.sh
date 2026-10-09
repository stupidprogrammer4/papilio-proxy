#!/usr/bin/env bash

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
trap deploy_failure_notice ERR
deploy_parse_args install "$@"
deploy_check_docker

[ -t 0 ] && [ -t 1 ] || deploy_fail 'Interactive installation needs a terminal to enter secrets privately.'
image_args=()
if [ -f "${DEPLOY_STATE_DIR}/compose.env" ]; then
    python_image="$(deploy_read_setting PYTHON_IMAGE)"
    if [ -n "$python_image" ]; then
        image_args+=(--build-arg "PYTHON_IMAGE=${python_image}")
    fi
fi
deploy_docker build --file "${DEPLOY_ROOT}/deployment/api.Dockerfile" \
    --tag papilio-proxy-api:local "${image_args[@]}" "$DEPLOY_ROOT"

configure_args=(--state-dir /state --host-state-dir "$DEPLOY_STATE_DIR")
if [ -n "$DEPLOY_PROJECT_OVERRIDE" ]; then
    configure_args+=(--project-name "$DEPLOY_PROJECT_OVERRIDE")
fi
deploy_docker run --rm --interactive --tty --user "$(id -u):$(id -g)" \
    --volume "${DEPLOY_STATE_DIR}:/state" --entrypoint python papilio-proxy-api:local \
    /opt/deployment/configure.py "${configure_args[@]}" "${DEPLOY_CONFIGURE_ARGS[@]}"
deploy_load_state
deploy_compose build api
deploy_compose build web
if [ "$DEPLOY_BOT_ENABLED" = true ]; then
    deploy_compose --profile bot build bot
fi

if [ "$DEPLOY_NO_START" = true ]; then
    printf '%s\n' 'Configuration and images prepared. Run scripts/deploy/start.sh with the same --state-dir.'
else
    start_args=(--state-dir "$DEPLOY_STATE_DIR")
    if [ "$DEPLOY_DOCKER_SUDO" = true ]; then
        start_args+=(--docker-sudo)
    fi
    "${DEPLOY_ROOT}/scripts/deploy/start.sh" "${start_args[@]}"
fi
