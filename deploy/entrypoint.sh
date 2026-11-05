#!/bin/sh
set -eu
umask 077
python manage.py migrate --noinput
cp -R /app/staticfiles/. /srv/static/
chmod -R a+rX /srv/static
exec gunicorn school_rmm.wsgi:application --bind 0.0.0.0:8000 \
    --workers 2 --threads 2 --timeout 60 --access-logfile - --error-logfile -
