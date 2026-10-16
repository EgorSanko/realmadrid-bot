#!/usr/bin/env bash
# Деплой «Мадридисты» на VPS. Повторяемый: можно запускать сколько угодно раз.
#
#   deploy/deploy.sh                 # обычный деплой
#   DOMAIN=example.ru deploy/deploy.sh
#   CERTBOT=1 deploy/deploy.sh       # + выпустить сертификат (только если DNS уже смотрит на сервер)
#
# Запускается локально (Git Bash / Linux / macOS). На сервере node не нужен:
# фронт собирается здесь, на сервер уезжает только dist.
set -euo pipefail

DOMAIN="${DOMAIN:-realmadridfan.ru}"        # домен — единственная настройка
SERVER="${SERVER:-root@81.17.154.4}"
REMOTE_DIR="${REMOTE_DIR:-/opt/rm-v2}"
SITE_NAME="${SITE_NAME:-realmadridfan}"      # имя файла в /etc/nginx/sites-available
API_PORT="${API_PORT:-8010}"
CERTBOT="${CERTBOT:-0}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEBROOT="$REMOTE_DIR/frontend-dist"
IMGROOT="$REMOTE_DIR/img-fallback"          # заглушки для /img/* (силуэт игрока, прозрачный 1×1)
IMG_CONF="/etc/nginx/conf.d/rmv2-img-cache.conf"  # proxy_cache_path (http-контекст), зона rmv2img
SSH="ssh -o BatchMode=yes $SERVER"

log() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

# ---------- 1. сборка фронта ----------
log "Сборка фронта"
cd "$ROOT/frontend"
[ -d node_modules ] || npm ci
npm run build

# ---------- 2. код бэкенда и compose ----------
log "Копирование backend и docker-compose.yml → $SERVER:$REMOTE_DIR"
$SSH "mkdir -p '$REMOTE_DIR'"
cd "$ROOT"
tar -czf - \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' \
  --exclude='.pytest_cache' --exclude='backend/tests' --exclude='backend/data' \
  docker-compose.yml backend \
  | $SSH "tar -xzf - -C '$REMOTE_DIR'"

# ---------- 3. статика (атомарная подмена каталога) ----------
log "Копирование frontend/dist → $WEBROOT"
tar -czf - -C "$ROOT/frontend/dist" . \
  | $SSH "set -e; rm -rf '$WEBROOT.new'; mkdir -p '$WEBROOT.new'; tar -xzf - -C '$WEBROOT.new';
          chmod -R a+rX '$WEBROOT.new';
          if [ -d '$WEBROOT' ]; then mv '$WEBROOT' '$WEBROOT.old'; fi;
          mv '$WEBROOT.new' '$WEBROOT'; rm -rf '$WEBROOT.old'"

# ---------- 4. backend в docker (api + collector) ----------
# том со снимками: создаём, но никогда не перезаписываем; владелец — uid пользователя app в образе
log "docker compose up -d --build"
$SSH "mkdir -p '$REMOTE_DIR/data' && chown 10001 '$REMOTE_DIR/data' && cd '$REMOTE_DIR' && docker compose up -d --build && docker compose ps"

# ---------- 5. сертификат (по желанию и только при живом DNS) ----------
if [ "$CERTBOT" = "1" ]; then
  if $SSH "getent hosts '$DOMAIN' >/dev/null"; then
    DOMAINS="-d $DOMAIN"
    if $SSH "getent hosts 'www.$DOMAIN' >/dev/null"; then DOMAINS="$DOMAINS -d www.$DOMAIN"; fi
    log "certbot certonly --nginx $DOMAINS"
    # certonly: certbot только получает сертификат, конфиг nginx пишем сами из шаблона
    $SSH "certbot certonly --nginx --non-interactive --agree-tos --keep-until-expiring $DOMAINS --cert-name '$DOMAIN'"
  else
    log "DNS для $DOMAIN ещё не указывает на сервер — certbot пропущен"
  fi
fi

# ---------- 6. nginx: только свои файлы, проверка перед reload ----------
log "заглушки картинок → $IMGROOT"
tar -czf - -C "$ROOT/deploy/img" . \
  | $SSH "set -e; mkdir -p '$IMGROOT'; tar -xzf - -C '$IMGROOT'; chmod -R a+rX '$IMGROOT'
          mkdir -p /var/cache/nginx/rmv2img; chown www-data /var/cache/nginx/rmv2img"
log "nginx: /etc/nginx/sites-available/$SITE_NAME"
if $SSH "test -f '/etc/letsencrypt/live/$DOMAIN/fullchain.pem'"; then
  HTTPS=1
  LISTEN="    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;"
  REDIRECT="server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}"
else
  HTTPS=0
  LISTEN="    listen 80;
    listen [::]:80;"
  REDIRECT=""
fi

CONF="$(cat "$ROOT/deploy/nginx.conf.template")"
CONF="${CONF//\{\{LISTEN\}\}/$LISTEN}"
CONF="${CONF//\{\{REDIRECT\}\}/$REDIRECT}"
CONF="${CONF//\{\{DOMAIN\}\}/$DOMAIN}"
CONF="${CONF//\{\{WEBROOT\}\}/$WEBROOT}"
CONF="${CONF//\{\{API_PORT\}\}/$API_PORT}"
CONF="${CONF//\{\{IMGROOT\}\}/$IMGROOT}"
IMGC="$(cat "$ROOT/deploy/nginx-img-cache.conf")"

AV="/etc/nginx/sites-available/$SITE_NAME"
EN="/etc/nginx/sites-enabled/$SITE_NAME"
# conf.d-файл с зоной кэша картинок (http-контекст) — кладём первым, сайт на него ссылается
printf '%s\n' "$IMGC" | $SSH "set -e
  if [ -f '$IMG_CONF' ]; then cp '$IMG_CONF' '/tmp/rmv2-img-cache.conf.prev'; else rm -f '/tmp/rmv2-img-cache.conf.prev'; fi
  cat > '/tmp/rmv2-img-cache.conf.new'"
printf '%s\n' "$CONF" | $SSH "set -e
  if [ -f '$AV' ]; then cp '$AV' '/tmp/$SITE_NAME.nginx.prev'; fi
  cat > '$AV.tmp'
  mv '/tmp/rmv2-img-cache.conf.new' '$IMG_CONF'
  mv '$AV.tmp' '$AV'
  ln -sfn '$AV' '$EN'
  if nginx -t; then
    systemctl reload nginx
    echo 'nginx: reload ok'
  else
    echo 'nginx -t FAILED — откатываю свои файлы' >&2
    if [ -f '/tmp/$SITE_NAME.nginx.prev' ]; then cp '/tmp/$SITE_NAME.nginx.prev' '$AV'; else rm -f '$EN' '$AV'; fi
    if [ -f '/tmp/rmv2-img-cache.conf.prev' ]; then cp '/tmp/rmv2-img-cache.conf.prev' '$IMG_CONF'; else rm -f '$IMG_CONF'; fi
    nginx -t && exit 1
  fi"

# ---------- 7. проверка ----------
log "Проверка"
if [ "$HTTPS" = "1" ]; then
  URL="https://$DOMAIN"; RESOLVE="$DOMAIN:443:${SERVER#*@}"
else
  URL="http://$DOMAIN"; RESOLVE="$DOMAIN:80:${SERVER#*@}"
fi
for i in 1 2 3 4 5 6 7 8 9 10; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --resolve "$RESOLVE" "$URL/api/health" || true)
  [ "$code" = "200" ] && break
  sleep 2
done
echo "GET $URL/       → $(curl -s -o /dev/null -w '%{http_code}' --resolve "$RESOLVE" "$URL/")"
echo "GET $URL/api/health → $code $(curl -s --resolve "$RESOLVE" "$URL/api/health")"
[ "$code" = "200" ] || { echo "health-check не прошёл" >&2; exit 1; }
log "Готово: $URL"
