#!/bin/sh
set -eu

python manage.py migrate
python manage.py bootstrap_support

gunicorn config.wsgi:application --bind "0.0.0.0:$PORT" --workers 2 --timeout 120 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT INT TERM

sleep 20
python manage.py bootstrap_datajud || echo "DataJud bootstrap deferred until the next restart."

wait "$server_pid"
