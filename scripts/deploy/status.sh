#!/usr/bin/env bash

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
trap deploy_failure_notice ERR
deploy_parse_args status "$@"
deploy_check_docker
deploy_load_state
deploy_compose --profile bot ps --all
deploy_show_url
