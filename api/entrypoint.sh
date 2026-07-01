#!/bin/sh
set -e
if [ -d /app/media ] && [ "$(stat -c %u /app/media)" != "1000" ]; then
    chown -R apiuser:apiuser /app/media
fi
exec gosu apiuser "$@"
