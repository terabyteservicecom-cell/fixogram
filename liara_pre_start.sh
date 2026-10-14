#!/bin/bash
set -e
mkdir -p database media
python manage.py migrate --noinput
python manage.py seed_roles
python manage.py ensure_admin