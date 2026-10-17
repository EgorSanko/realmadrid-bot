#!/usr/bin/env bash
# Слежение за сборщиком (cron раз в 5 минут, см. deploy/cron/rm-v2).
#
# Сердцебиение сборщика (data/collector.heartbeat, пишется каждые ~5 с) старше MAX_AGE (5 мин) или
# контейнер не healthy → docker compose restart collector и запись в /var/log/rm-v2-watchdog.log.
# Только что запущенный контейнер (health=starting, моложе GRACE) не трогаем.
#
# Уведомление в Telegram — выключено (WATCHDOG_TG=0): бот пользователям ничего не рассылает.
# WATCHDOG_TG=1 — сообщение о перезапуске только админам из ADMIN_IDS (.env, нужен и BOT_TOKEN),
# не чаще раза в час, только через SOCKS-туннель (api.telegram.org из России напрямую не открывается).
#
# Переменные (для проверки): REMOTE_DIR, HEARTBEAT, MAX_AGE, GRACE, CONTAINER, WATCHDOG_LOG, STATE_DIR,
# DOCKER, ENV_FILE, WATCHDOG_TG, TG_PROXY, TG_EVERY, NOW.
set -uo pipefail

REMOTE_DIR="${REMOTE_DIR:-/opt/rm-v2}"
HEARTBEAT="${HEARTBEAT:-$REMOTE_DIR/data/collector.heartbeat}"
MAX_AGE="${MAX_AGE:-300}"
GRACE="${GRACE:-600}"
CONTAINER="${CONTAINER:-rm-v2-collector}"
SERVICE="${SERVICE:-collector}"
WATCHDOG_LOG="${WATCHDOG_LOG:-/var/log/rm-v2-watchdog.log}"
STATE_DIR="${STATE_DIR:-/var/lib/rm-v2}"
DOCKER="${DOCKER:-docker}"
ENV_FILE="${ENV_FILE:-$REMOTE_DIR/.env}"
WATCHDOG_TG="${WATCHDOG_TG:-0}"
TG_PROXY="${TG_PROXY:-socks5h://127.0.0.1:1080}"
TG_EVERY="${TG_EVERY:-3600}"
NOW="${NOW:-$(date +%s)}"

log() { printf '%s watchdog: %s\n' "$(date -u +%FT%TZ)" "$*" >>"$WATCHDOG_LOG"; }

mkdir -p "$STATE_DIR"
# два запуска разом (долгий restart) — второй выходит
exec 9>"$STATE_DIR/watchdog.lock"
if command -v flock >/dev/null 2>&1 && ! flock -n 9; then
  exit 0
fi

# --- сердцебиение ---
hb_age=""
if [ -r "$HEARTBEAT" ]; then
  hb="$(cut -d. -f1 <"$HEARTBEAT" 2>/dev/null | tr -cd '0-9')"
  [ -n "$hb" ] && hb_age=$(( NOW - hb ))
fi

# --- состояние контейнера ---
health="$($DOCKER inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null)" || health="missing"
health="${health:-missing}"
started="$($DOCKER inspect -f '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null)" || started=""
up_s=""
if [ -n "$started" ]; then
  st="$(date -d "$started" +%s 2>/dev/null)" && up_s=$(( NOW - st ))
fi

reason=""
if [ -z "$hb_age" ]; then
  reason="нет сердцебиения ($HEARTBEAT)"
elif [ "$hb_age" -gt "$MAX_AGE" ]; then
  reason="сердцебиение ${hb_age} с назад (> ${MAX_AGE})"
fi
if [ "$health" != "healthy" ]; then
  reason="${reason:+$reason; }контейнер $health"
fi

[ -z "$reason" ] && exit 0

# только что (пере)запущен и ещё проходит start_period — подождём следующего раза
if [ "$health" = "starting" ] && [ -n "$up_s" ] && [ "$up_s" -lt "$GRACE" ]; then
  log "пропуск: $reason; контейнер запущен ${up_s} с назад"
  exit 0
fi

log "ПЕРЕЗАПУСК collector: $reason"
if out="$(cd "$REMOTE_DIR" && $DOCKER compose restart "$SERVICE" 2>&1)"; then
  log "restart ok"
  result="перезапущен"
else
  log "restart не удался: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-300) — пробую up -d"
  if out="$(cd "$REMOTE_DIR" && $DOCKER compose up -d "$SERVICE" 2>&1)"; then
    log "up -d ok"
    result="поднят заново (up -d)"
  else
    log "up -d не удался: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-300)"
    result="НЕ поднят"
  fi
fi

# --- уведомление админу (по желанию) ---
[ "$WATCHDOG_TG" = "1" ] || exit 0
env_get() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"' \r"; }
token="$(env_get BOT_TOKEN)"
admins="$(env_get ADMIN_IDS | tr ',;' '  ')"
if [ -z "$token" ] || [ -z "$admins" ]; then
  log "telegram: нет BOT_TOKEN или ADMIN_IDS — не отправляю"
  exit 0
fi
last="$(cat "$STATE_DIR/watchdog.tg" 2>/dev/null | tr -cd '0-9')"
if [ -n "$last" ] && [ $(( NOW - last )) -lt "$TG_EVERY" ]; then
  log "telegram: уже писали $(( NOW - last )) с назад — не чаще раза в час"
  exit 0
fi
text="Мадридиста: сборщик ${result}. Причина: ${reason}. $(hostname 2>/dev/null) $(date -u +%H:%MZ)"
sent=0
for id in $admins; do
  case "$id" in (*[!0-9-]*|'') continue ;; esac
  # токен — через конфиг curl на stdin, а не в аргументах (не светится в ps)
  if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token" |
      curl -sS -m 20 -o /dev/null -w '%{http_code}' -K - --proxy "$TG_PROXY" \
        --data-urlencode "chat_id=$id" --data-urlencode "text=$text" | grep -q '^200$'; then
    sent=$(( sent + 1 ))
  fi
done
echo "$NOW" >"$STATE_DIR/watchdog.tg"
log "telegram: отправлено админам: $sent"
exit 0
