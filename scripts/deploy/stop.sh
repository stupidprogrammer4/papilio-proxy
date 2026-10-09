#!/usr/bin/env bash

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
trap deploy_failure_notice ERR
deploy_parse_args stop "$@"
deploy_check_docker
deploy_load_state
deploy_compose --profile bot stop
printf '%s\n' 'Project services stopped. Configuration and database volumes are preserved.'
