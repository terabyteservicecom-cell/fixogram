#!/bin/bash
set -euo pipefail
cd /var/www/tamirneshan
set -a
. /etc/tamirneshan.env
set +a
chown -R www-data:www-data talent config templates/talent
PYTHONPATH=/var/www/tamirneshan ./.venv/bin/python manage.py migrate --noinput
PYTHONPATH=/var/www/tamirneshan ./.venv/bin/python manage.py collectstatic --noinput
systemctl restart tamirneshan
systemctl is-active tamirneshan
curl -s -H "Host: fixogram.ir" http://127.0.0.1/login/ | grep -q "فراموشی" && echo forgot_username_ok
