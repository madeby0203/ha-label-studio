#!/usr/bin/with-contenv sh
# with-contenv passes the container environment (SUPERVISOR_TOKEN, TZ) that s6-overlay keeps from CMD.
set -eu

mkdir -p /data
exec python3 /app/app.py
