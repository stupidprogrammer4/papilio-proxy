#!/bin/sh
set -eu
# Read private bind-mounted files before the native entrypoint drops privileges.
MYSQL_ROOT_PASSWORD=$(cat /run/secrets/mysql-root-password)
MYSQL_PASSWORD=$(cat /run/secrets/mysql-password)
export MYSQL_ROOT_PASSWORD MYSQL_PASSWORD
exec /usr/local/bin/docker-entrypoint.sh "$@"
