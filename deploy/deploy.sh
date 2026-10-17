#!/usr/bin/env bash
# Деплой «Мадридисты» на VPS. Повторяемый: можно запускать сколько угодно раз.
#
#   deploy/deploy.sh                 # обычный деплой
#   DOMAIN=example.ru deploy/deploy.sh
#   CERTBOT=1 deploy/deploy.sh       # + выпустить сертификат (только если DNS уже смотрит на сервер)
#   INSTALL_CRON=1 deploy/deploy.sh  # + cron (бэкап 03:40, watchdog каждые 5 мин) и logrotate для /var/log/rm-v2-*.log
#
# Скрипты deploy/backup.sh и deploy/watchdog.sh копируются в $REMOTE_DIR/deploy при каждом деплое,
# но запускаются по расписанию, только если хоть раз был деплой с INSTALL_CRON=1.
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
INSTALL_CRON="${INSTALL_CRON:-0}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEBROOT="$REMOTE_DIR/frontend-dist"
IMGROOT="$REMOTE_DIR/img-fallback"          # заглушки для /img/* (силуэт игрока, прозрачный 1×1)
DATAROOT="$REMOTE_DIR/data"                 # том данных; nginx читает из него только avatars/ (/img/avatar/*)
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
  docker-compose.yml backend deploy/backup.sh deploy/watchdog.sh \
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
# avatars/ — аватары пользователей: пишет сборщик (uid 10001), читает nginx на хосте (www-data)
# GIT_SHA — версия сборки для /api/health (compose build args → ENV BUILD_SHA); незакоммиченные правки — «-dirty»
GIT_SHA="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ "$GIT_SHA" != "unknown" ] && [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then GIT_SHA="$GIT_SHA-dirty"; fi
log "сборка $GIT_SHA"
$SSH "chmod 755 '$REMOTE_DIR/deploy/backup.sh' '$REMOTE_DIR/deploy/watchdog.sh'"
$SSH "mkdir -p '$REMOTE_DIR/data/avatars' && chown 10001 '$REMOTE_DIR/data' '$REMOTE_DIR/data/avatars' && chmod 755 '$REMOTE_DIR/data' '$REMOTE_DIR/data/avatars' && cd '$REMOTE_DIR' && GIT_SHA='$GIT_SHA' docker compose up -d --build && docker compose ps"

# ---------- 4b. cron и logrotate (только по флагу) ----------
if [ "$INSTALL_CRON" = "1" ]; then
  log "cron → /etc/cron.d/rm-v2, logrotate → /etc/logrotate.d/rm-v2"
  CRON="$(cat "$ROOT/deploy/cron/rm-v2")"
  CRON="${CRON//\{\{REMOTE_DIR\}\}/$REMOTE_DIR}"
  printf '%s\n' "$CRON" | $SSH "set -e
    mkdir -p '$REMOTE_DIR/backups' /var/lib/rm-v2
    chmod 711 '$REMOTE_DIR/backups'
    cat > /etc/cron.d/rm-v2.tmp
    chmod 644 /etc/cron.d/rm-v2.tmp
    mv /etc/cron.d/rm-v2.tmp /etc/cron.d/rm-v2"
  cat "$ROOT/deploy/logrotate/rm-v2" | $SSH "set -e
    cat > /tmp/rm-v2.logrotate.new
    if logrotate -d /tmp/rm-v2.logrotate.new >/dev/null 2>&1; then
      install -m 644 /tmp/rm-v2.logrotate.new /etc/logrotate.d/rm-v2; rm -f /tmp/rm-v2.logrotate.new
      echo 'logrotate: ok'
    else
      echo 'logrotate -d FAILED — /etc/logrotate.d/rm-v2 не тронут' >&2; rm -f /tmp/rm-v2.logrotate.new; exit 1
    fi"
  $SSH "cat /etc/cron.d/rm-v2 | grep -v '^#' | grep ."
else
  log "cron/logrotate не трогаю (INSTALL_CRON=1 — поставить бэкап и watchdog)"
fi

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
  SCHEME=https
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
    # сразу на https и без www — одним редиректом
    location / { return 301 https://$DOMAIN\$request_uri; }
}"
else
  HTTPS=0
  SCHEME=http
  LISTEN="    listen 80;
    listen [::]:80;"
  REDIRECT=""
fi

CONF="$(cat "$ROOT/deploy/nginx.conf.template")"
CONF="${CONF//\{\{LISTEN\}\}/$LISTEN}"
CONF="${CONF//\{\{REDIRECT\}\}/$REDIRECT}"
CONF="${CONF//\{\{SCHEME\}\}/$SCHEME}"
CONF="${CONF//\{\{DOMAIN\}\}/$DOMAIN}"
CONF="${CONF//\{\{WEBROOT\}\}/$WEBROOT}"
CONF="${CONF//\{\{API_PORT\}\}/$API_PORT}"
CONF="${CONF//\{\{IMGROOT\}\}/$IMGROOT}"
CONF="${CONF//\{\{DATAROOT\}\}/$DATAROOT}"
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
