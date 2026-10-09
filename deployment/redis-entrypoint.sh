#!/bin/sh
set -eu
umask 077
password=$(cat /run/secrets/redis-password)
case "$password" in ''|*[!A-Za-z0-9_-]*) exit 1;; esac
printf 'bind 0.0.0.0\nprotected-mode yes\nappendonly yes\ndir /data\nrequirepass %s\n' "$password" > /tmp/papilio-redis.conf
chown redis:redis /tmp/papilio-redis.conf
exec /usr/local/bin/docker-entrypoint.sh redis-server /tmp/papilio-redis.conf
