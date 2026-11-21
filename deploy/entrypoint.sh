#!/bin/sh
# Runs before the web server. Migrations and static files are done here, at start-up,
# so the client's own static files are included. Only the web container sets
# EMS_RUN_MIGRATIONS=true, so the worker never races it.
set -e

if [ "${EMS_RUN_MIGRATIONS:-false}" = "true" ]; then
    python manage.py migrate --noinput
    python manage.py sync_roles
    python manage.py collectstatic --noinput
fi

exec "$@"
