#!/bin/sh
# Run by systemd whenever ledgames crashes. If it's running a fresh update
# that never ran healthily, go back to the previous release and remember the
# bad one so it isn't installed again. Otherwise do nothing (systemd restarts
# the service as usual).
set -e
cd /opt/ledgames
current=$(basename "$(readlink current)")
previous=$(readlink previous 2>/dev/null || true)
confirmed=$(cat confirmed 2>/dev/null || true)
if [ -z "$previous" ] || [ "$current" = "$confirmed" ] || [ "$(basename "$previous")" = "$current" ]; then
  echo "ledgames: not rolling back $current"
  exit 0
fi
echo "ledgames: $current crashed, going back to $(basename "$previous")"
echo "$current" > failed
ln -sfn "$previous" current.tmp
mv -T current.tmp current
systemctl reset-failed ledgames
systemctl start ledgames
