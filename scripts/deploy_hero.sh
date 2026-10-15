#!/bin/bash
set -euo pipefail
cd /var/www/tamirneshan
set -a; . /etc/tamirneshan.env; set +a
chown www-data:www-data templates/talent/home.html templates/talent/base.html talent/static/talent/style.css talent/copy.py
PYTHONPATH=/var/www/tamirneshan ./.venv/bin/python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from talent.models import HomeCopy
from talent.copy import DEFAULTS
row, _ = HomeCopy.objects.get_or_create(pk=1)
row.headline = DEFAULTS["headline"]
row.lead = DEFAULTS["lead"]
if DEFAULTS.get("eyebrow"):
    row.eyebrow = DEFAULTS["eyebrow"]
row.save()
print("headline:", row.headline)
PY
PYTHONPATH=/var/www/tamirneshan ./.venv/bin/python manage.py collectstatic --noinput
systemctl restart tamirneshan
systemctl is-active tamirneshan
