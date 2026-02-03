#!/bin/sh
set -e

python manage.py wait_for_db
python manage.py migrate
python manage.py ingest_initial_data

exec python manage.py runserver 0.0.0.0:8000
