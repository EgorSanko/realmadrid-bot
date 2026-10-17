#!/usr/bin/env bash
# Ежедневный бэкап баз SQLite «Мадридисты» (cron 03:40 по серверу, см. deploy/cron/rm-v2).
#
#   predictions.db — главное: пользователи, прогнозы, очки, лиги;
#   rm.sqlite3     — снимки сборщика (восстанавливаются сами, но с копией быстрее).
#
# Горячая копия: онлайн-бэкап SQLite (sqlite3 ".backup", если есть CLI; иначе тот же API через python3 —
# на сервере sqlite3 CLI не установлен). Читатели и писатели в режиме WAL не блокируются.
# Копия проверяется PRAGMA quick_check, сжимается gzip и кладётся в $BACKUP_DIR/YYYY-MM-DD/.
# Хранится KEEP_DAYS дней (сегодняшний включительно), старые каталоги удаляются.
#
# Копию делает владелец файла базы (uid 10001 из контейнера): если root откроет WAL-базу,
# он может создать -wal/-shm со своим владельцем — и API потеряет запись.
#
# Восстановление: остановить api и collector, gunzip -c predictions.db.gz > data/predictions.db,
# chown 10001 data/predictions.db, удалить data/predictions.db-wal и -shm, запустить.
#
# Переменные (для проверки на копии): DATA_DIR, BACKUP_DIR, KEEP_DAYS, DBS, PYTHON, TODAY.
set -euo pipefail

DATA_DIR="${DATA_DIR:-/opt/rm-v2/data}"
BACKUP_DIR="${BACKUP_DIR:-/opt/rm-v2/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
DBS="${DBS:-predictions.db rm.sqlite3}"
PYTHON="${PYTHON:-python3}"
TODAY="${TODAY:-$(date -u +%F)}"

log() { printf '%s backup: %s\n' "$(date -u +%FT%TZ)" "$*"; }

cd /   # cron стартует в /root — от имени uid 10001 туда не зайти

mkdir -p "$BACKUP_DIR"
# 711: владелец базы (uid 10001) заходит во временный каталог по имени, но не видит список;
# каталоги дней — 700, файлы — 600 (root)
chmod 711 "$BACKUP_DIR" 2>/dev/null || true

# один бэкап за раз
exec 9>"$BACKUP_DIR/.lock"
if command -v flock >/dev/null 2>&1 && ! flock -n 9; then
  log "уже идёт другой бэкап — выхожу"
  exit 0
fi

# запуск от имени владельца файла базы (root на сервере → uid 10001); не root — как есть.
# Даже открытие «только для чтения» создаёт рядом с WAL-базой -wal/-shm, если их нет, — от root это
# сломало бы запись API, поэтому root без setpriv базу не трогает.
as_owner() {
  local owner="$1"; shift
  if [ "$(id -u)" = "0" ] && [ "$owner" != "0" ]; then
    if ! command -v setpriv >/dev/null 2>&1; then
      echo "нет setpriv: от root копировать базу uid $owner небезопасно" >&2
      return 1
    fi
    setpriv --reuid="$owner" --regid="$owner" --clear-groups -- "$@"
  else
    "$@"
  fi
}

# онлайн-копия src → dst, потом quick_check и журнал DELETE (один файл, без -wal)
hot_copy() {
  local src="$1" dst="$2"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$src" ".timeout 10000" ".backup '$dst'"
    [ "$(sqlite3 "$dst" 'PRAGMA quick_check;')" = "ok" ] || { echo "quick_check не ok: $dst" >&2; return 1; }
    sqlite3 "$dst" 'PRAGMA journal_mode=DELETE;' >/dev/null
  else
    "$PYTHON" - "$src" "$dst" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=10)   # только чтение: файлы рядом с базой не создаём
d = sqlite3.connect(dst)
s.backup(d)                       # тот же онлайн-бэкап SQLite, что и ".backup" в CLI
s.close()
ok = d.execute("PRAGMA quick_check").fetchone()[0]
if ok != "ok":
    sys.exit(f"quick_check: {ok}")
d.execute("PRAGMA journal_mode=DELETE")
d.close()
PY
  fi
}

export -f hot_copy
export PYTHON

dest="$BACKUP_DIR/$TODAY"
tmp="$BACKUP_DIR/.tmp-$TODAY-$$"
rm -rf "$tmp"
mkdir -p "$tmp"
trap 'rm -rf "$tmp"' EXIT

fail=0
for db in $DBS; do
  src="$DATA_DIR/$db"
  if [ ! -f "$src" ]; then
    log "нет $src — пропускаю"
    fail=1
    continue
  fi
  owner="$(stat -c %u "$src" 2>/dev/null || echo 0)"
  # во временный каталог пишет владелец базы; потом всё забирает root (chown ниже)
  if [ "$(id -u)" = "0" ] && [ "$owner" != "0" ]; then chown "$owner" "$tmp"; fi
  t0=$(date +%s)
  if ! as_owner "$owner" bash -c 'hot_copy "$@"' _ "$src" "$tmp/$db" 2>"$tmp/$db.err"; then
    log "ОШИБКА копии $db: $(tr '\n' ' ' <"$tmp/$db.err" | cut -c1-300)"
    rm -f "$tmp/$db" "$tmp/$db.err"
    fail=1
    continue
  fi
  rm -f "$tmp/$db.err"
  gzip -9 -f "$tmp/$db"
  log "$db: $(stat -c %s "$src") Б → $(stat -c %s "$tmp/$db.gz") Б gzip за $(( $(date +%s) - t0 )) с"
done

if [ "$(id -u)" = "0" ]; then chown -R 0:0 "$tmp"; fi
chmod 700 "$tmp"
chmod 600 "$tmp"/* 2>/dev/null || true

if ls "$tmp"/*.gz >/dev/null 2>&1; then
  # повторный запуск в тот же день заменяет копию дня целиком
  rm -rf "$dest.old"
  [ -d "$dest" ] && mv "$dest" "$dest.old"
  mv "$tmp" "$dest"
  rm -rf "$dest.old"
  trap - EXIT
  log "готово: $dest"
else
  log "ни одной копии не сделано"
  fail=1
fi

# хранение: последние KEEP_DAYS дней по имени каталога (YYYY-MM-DD сравниваются как строки)
cutoff="$(date -u -d "$TODAY - $((KEEP_DAYS - 1)) days" +%F)"
for d in "$BACKUP_DIR"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  if [[ "$name" < "$cutoff" ]]; then
    rm -rf "$d"
    log "удалён старый $name"
  fi
done
# брошенные временные каталоги прерванных запусков
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '.tmp-*' -mmin +120 -exec rm -rf {} + 2>/dev/null || true

exit "$fail"
