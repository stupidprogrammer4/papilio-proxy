#!/bin/sh
set -eu

source_dir=/etc/letsencrypt/live/bot.amupouya.org
target_dir=/opt/papilio-proxy/data/xray/certs

test -s "$source_dir/fullchain.pem"
test -s "$source_dir/privkey.pem"
install -d -m 0700 "$target_dir"
chown 65532:65532 "$target_dir"
install -m 0400 "$source_dir/fullchain.pem" "$target_dir/fullchain.pem.next"
install -m 0400 "$source_dir/privkey.pem" "$target_dir/privkey.pem.next"
chown 65532:65532 "$target_dir/fullchain.pem.next" "$target_dir/privkey.pem.next"
mv -f "$target_dir/fullchain.pem.next" "$target_dir/fullchain.pem"
mv -f "$target_dir/privkey.pem.next" "$target_dir/privkey.pem"

if docker container inspect papilio-xray-1 >/dev/null 2>&1; then
    docker restart papilio-xray-1 >/dev/null
fi
