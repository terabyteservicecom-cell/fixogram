#!/bin/bash
set -euo pipefail
cd /var/www/tamirneshan
R=https://raw.githubusercontent.com/terabyteservicecom-cell/fixogram/main
mkdir -p templates/talent talent/migrations config scripts
for path in \
  talent/views.py \
  talent/forms.py \
  talent/sms.py \
  talent/urls.py \
  talent/migrations/0038_normalize_unique_phones.py \
  config/settings.py \
  templates/talent/enter.html \
  templates/talent/forgot_username.html \
  templates/talent/forgot_username_code.html \
  templates/talent/forgot_username_done.html \
  scripts/deploy_app.sh
do
  curl -fsSL -o "$path" "$R/$path"
done
chmod +x scripts/deploy_app.sh
bash scripts/deploy_app.sh
