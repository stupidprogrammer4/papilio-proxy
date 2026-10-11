#!/bin/sh
set -eu
umask 077
password=$(cat /run/secrets/redis-password)
case "$password" in ''|*[!A-Za-z0-9_-]*) exit 1;; esac
# A root-owned private directory supports restart without writable sticky-/tmp
# files and lets Redis read its credentials without changing the configuration.
mkdir -p /run/papilio-redis
chown root:redis /run/papilio-redis
chmod 750 /run/papilio-redis
printf 'bind 0.0.0.0\nprotected-mode yes\nappendonly yes\ndir /data\nrequirepass %s\n' "$password" > /run/papilio-redis/redis.conf
chown root:redis /run/papilio-redis/redis.conf
chmod 640 /run/papilio-redis/redis.conf
exec /usr/local/bin/docker-entrypoint.sh redis-server /run/papilio-redis/redis.conf
