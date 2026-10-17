#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RuStore Public API — публикация «Мадридиста» (ru.realmadridfan.app).

Только стандартная библиотека; если установлен пакет `cryptography` — подпись через него,
иначе — встроенная реализация RSA PKCS#1 v1.5 + SHA-512 (ключ никуда не копируется,
на диск не пишется).

Ключи (по умолчанию, переопределяются переменными окружения):
  RUSTORE_KEY_FILE     — base64 PKCS#8 DER приватного ключа RSA
  RUSTORE_KEY_ID_FILE  — keyId

Чтение (безопасно):
  python publish.py auth
  python publish.py apps
  python publish.py status [--package PKG]
  python publish.py version-detail --version-id ID

Запись (без --yes только печатает, что будет сделано):
  python publish.py draft [--card card.json] [--whats-new FILE] [--moder-file FILE] [--yes]
  python publish.py edit --card card.json [--version-id ID] [--yes]
  python publish.py upload-screens <папка> [--version-id ID] [--yes]
  python publish.py upload-icon <icon.png> [--version-id ID] [--yes]
  python publish.py upload-apk <app.apk> [--version-id ID] [--yes]
  python publish.py upload-aab <app.aab> [--version-id ID] [--yes]
  python publish.py commit [--version-id ID] [--yes]
  python publish.py delete-draft [--version-id ID] [--yes]

Запускать с PYTHONIOENCODING=utf-8 (Windows-консоль).
Справка API: https://www.rustore.ru/help/work-with-rustore-api/api-upload-publication-app/
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://public-api.rustore.ru"
PACKAGE = "ru.realmadridfan.app"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_KEY_FILE = r"C:\Users\egor3\Projects\f1\f1hub-app\.secrets\rustore_api_private_key.txt"
DEFAULT_KEY_ID_FILE = r"C:\Users\egor3\Projects\f1\f1hub-app\.secrets\rustore_api_key_id.txt"
DEFAULT_WHATS_NEW = os.path.join(HERE, "whats-new.txt")
DEFAULT_MODER_FILE = r"C:\Users\egor3\.keystores\realmadridfan-rustore-review.txt"

# Лимиты из справки RuStore API (create-draft-version / upload-screenshot-v2 / apk-icon-upload)
LIM_APP_NAME = 50          # в консоли — 30, проверяем по более строгому
LIM_APP_NAME_CONSOLE = 30
LIM_SHORT = 80
LIM_FULL = 4000
LIM_WHATS_NEW = 5000
LIM_MODER = 180
SCREEN_MAX_BYTES = 5 * 1024 * 1024
ICON_MAX_BYTES = 3 * 1024 * 1024
PKG_MAX_BYTES = 5 * 1024 ** 3
AGE_VALUES = {"0+", "6+", "12+", "16+", "18+"}


def die(msg, code=1):
    print("ОШИБКА: " + msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- подпись
def _der_read(buf, pos):
    tag = buf[pos]
    pos += 1
    ln = buf[pos]
    pos += 1
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(buf[pos:pos + n], "big")
        pos += n
    return tag, buf[pos:pos + ln], pos + ln


def _der_seq_items(content):
    items, pos = [], 0
    while pos < len(content):
        tag, val, pos = _der_read(content, pos)
        items.append((tag, val))
    return items


def _rsa_from_pkcs8(der):
    """PKCS#8 PrivateKeyInfo -> (n, d). Поддерживается и голый PKCS#1."""
    tag, body, _ = _der_read(der, 0)
    items = _der_seq_items(body)
    if len(items) >= 3 and items[1][0] == 0x30 and items[2][0] == 0x04:
        tag, body, _ = _der_read(items[2][1], 0)  # PKCS#1 RSAPrivateKey
        items = _der_seq_items(body)
    ints = [int.from_bytes(v, "big") for t, v in items if t == 0x02]
    # version, n, e, d, p, q, dp, dq, qinv
    return ints[1], ints[3]


def _sign_pure(der, message):
    n, d = _rsa_from_pkcs8(der)
    k = (n.bit_length() + 7) // 8
    digest_info = bytes.fromhex("3051300d060960864801650304020305000440") + hashlib.sha512(message).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(digest_info) - 3) + b"\x00" + digest_info
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def sign(der, message):
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_der_private_key
    except ImportError:
        return _sign_pure(der, message)
    key = load_der_private_key(der, None)
    return key.sign(message, padding.PKCS1v15(), hashes.SHA512())


def get_token():
    key_file = os.environ.get("RUSTORE_KEY_FILE", DEFAULT_KEY_FILE)
    kid_file = os.environ.get("RUSTORE_KEY_ID_FILE", DEFAULT_KEY_ID_FILE)
    if not os.path.isfile(key_file) or not os.path.isfile(kid_file):
        die("не найден файл ключа или keyId (RUSTORE_KEY_FILE / RUSTORE_KEY_ID_FILE)")
    with open(kid_file, encoding="utf-8") as f:
        kid = f.read().strip()
    with open(key_file, encoding="utf-8") as f:
        der = base64.b64decode("".join(f.read().split()))
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).isoformat(timespec="milliseconds")
    sig = base64.b64encode(sign(der, (kid + ts).encode())).decode()
    del der
    st, resp = _http("POST", API + "/public/auth/", json_body={"keyId": kid, "timestamp": ts, "signature": sig})
    tok = ((resp or {}).get("body") or {}).get("jwe") if isinstance(resp, dict) else None
    if not tok:
        msg = resp.get("message") if isinstance(resp, dict) else str(resp)[:200]
        die("авторизация не удалась: HTTP %s, %s" % (st, msg))
    return tok


# ---------------------------------------------------------------- HTTP
def _http(method, url, json_body=None, token=None, files=None, timeout=120):
    headers = {}
    data = None
    if token:
        headers["Public-Token"] = token
    if files:
        boundary = "----rustore" + uuid.uuid4().hex
        parts = []
        for field, (fname, content, ctype) in files.items():
            parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                          "Content-Type: %s\r\n\r\n" % (boundary, field, fname, ctype)).encode())
            parts.append(content)
            parts.append(b"\r\n")
        parts.append(("--%s--\r\n" % boundary).encode())
        data = b"".join(parts)
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    elif json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            st = r.status
    except urllib.error.HTTPError as e:
        raw, st = e.read(), e.code
    except urllib.error.URLError as e:
        die("сеть: %s" % e.reason)
    try:
        return st, json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        return st, raw.decode("utf-8", "replace")[:500]


def api(method, path, token, **kw):
    st, resp = _http(method, API + path, token=token, **kw)
    ok = 200 <= st < 300 and (not isinstance(resp, dict) or resp.get("code") in (None, "OK"))
    return ok, st, resp


def show_err(st, resp):
    if isinstance(resp, dict):
        print("  HTTP %s: %s %s" % (st, resp.get("code"), resp.get("message")))
    else:
        print("  HTTP %s: %s" % (st, resp))


# ---------------------------------------------------------------- изображения
def image_size(path):
    with open(path, "rb") as f:
        head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return "png", w, h
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    break
                marker = b[0]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    continue
                seg_len = struct.unpack(">H", f.read(2))[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    f.read(1)
                    h, w = struct.unpack(">HH", f.read(4))
                    return "jpg", w, h
                f.seek(seg_len - 2, 1)
    return None, 0, 0


def ctype_for(path):
    ext = os.path.splitext(path)[1].lower()
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".apk": "application/vnd.android.package-archive", ".aab": "application/octet-stream"}.get(ext, "application/octet-stream")


# ---------------------------------------------------------------- тексты
def read_text(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read().strip()


def read_moder(path):
    if not os.path.isfile(path):
        die("нет файла комментария модератору: %s (укажите --moder-file)" % path)
    txt = read_text(path)
    for line in txt.splitlines():
        if line.strip().lower().startswith("moderinfo:"):
            return line.split(":", 1)[1].strip()
    print("ВНИМАНИЕ: строки 'moderInfo:' не найдено — используется весь текст файла.")
    return txt


def check_len(name, value, limit):
    n = len(value)
    if n > limit:
        die("%s: %d символов > лимита %d" % (name, n, limit))
    print("  %s: %d/%d символов" % (name, n, limit))


def load_card(path):
    with open(path, encoding="utf-8-sig") as f:
        card = json.load(f)
    allowed = {"appName", "appType", "categories", "ageLegal", "shortDescription", "fullDescription",
               "whatsNew", "moderInfo", "seoTagIds", "publishType", "publishDateTime", "partialValue",
               "developerContacts", "faq", "privacyExplanation", "privacyDataTypes", "video", "backgroundVideo"}
    extra = set(card) - allowed
    if extra:
        die("неизвестные поля в card.json: %s" % ", ".join(sorted(extra)))
    if "appName" in card:
        check_len("appName", card["appName"], LIM_APP_NAME)
        if len(card["appName"]) > LIM_APP_NAME_CONSOLE:
            print("  ВНИМАНИЕ: в консоли лимит названия %d символов" % LIM_APP_NAME_CONSOLE)
    if "shortDescription" in card:
        check_len("shortDescription", card["shortDescription"], LIM_SHORT)
    if "fullDescription" in card:
        check_len("fullDescription", card["fullDescription"], LIM_FULL)
    if "ageLegal" in card and card["ageLegal"] not in AGE_VALUES:
        die("ageLegal должен быть одним из %s" % sorted(AGE_VALUES))
    if "categories" in card and len(card["categories"]) > 2:
        die("categories: не более 2")
    if "seoTagIds" in card and len(card["seoTagIds"]) > 5:
        die("seoTagIds: не более 5")
    return card


# ---------------------------------------------------------------- команды
def find_draft(token, package):
    ok, st, resp = api("GET", "/public/v1/application/%s/version?versionStatuses=DRAFT&filterTestingType=ALL&page=0&size=20"
                       % package, token)
    if not ok:
        show_err(st, resp)
        return None
    content = ((resp.get("body") or {}).get("content")) or []
    drafts = [v for v in content if v.get("versionStatus") == "DRAFT"]
    return drafts[0]["versionId"] if drafts else None


def resolve_version(args, token):
    if args.version_id:
        return args.version_id
    vid = find_draft(token, args.package)
    if not vid:
        die("черновик не найден — сначала `draft` или укажите --version-id")
    print("Черновик: versionId=%s" % vid)
    return vid


def cmd_auth(args):
    get_token()
    print("OK, токен получен")


def cmd_apps(args):
    token = get_token()
    ok, st, resp = api("GET", "/public/v1/application?pagination=true&pageSize=100", token)
    if not ok:
        show_err(st, resp)
        sys.exit(1)
    content = (resp.get("body") or {}).get("content") or []
    print("Приложений: %d" % len(content))
    for a in content:
        print("  %-40s %-32s %-14s v%s (%s)" % (a.get("appName"), a.get("packageName"), a.get("appStatus"),
                                               a.get("versionName"), a.get("versionCode")))


def cmd_status(args):
    token = get_token()
    pkg = args.package
    ok, st, resp = api("GET", "/public/v1/application?appPackage=%s" % urllib.parse.quote(pkg), token)
    apps = ((resp.get("body") or {}).get("content") or []) if ok and isinstance(resp, dict) else []
    apps = [a for a in apps if a.get("packageName") == pkg]
    if not apps:
        print("Приложение %s в аккаунте НЕ найдено (список приложений: HTTP %s)." % (pkg, st))
        print("Карточку нужно создать в RuStore Консоли и загрузить первую версию там.")
    for a in apps:
        print("Приложение: %s | %s | статус %s | v%s (%s) | appId %s" % (
            a.get("appName"), a.get("packageName"), a.get("appStatus"), a.get("versionName"),
            a.get("versionCode"), a.get("appId")))
    ok, st, resp = api("GET", "/public/v1/application/%s/version?filterTestingType=ALL&page=0&size=20" % pkg, token)
    if not ok:
        print("Версии: недоступны")
        show_err(st, resp)
        return
    vers = (resp.get("body") or {}).get("content") or []
    print("Версий: %d" % len(vers))
    for v in vers:
        print("  id %-9s %-22s v%s (%s) %s publish=%s" % (v.get("versionId"), v.get("versionStatus"),
                                                    v.get("versionName"), v.get("versionCode"),
                                                    v.get("appName"), v.get("publishType")))


def cmd_version_detail(args):
    token = get_token()
    vid = resolve_version(args, token)
    ok, st, resp = api("GET", "/public/v2/application/%s/version/%s" % (args.package, vid), token)
    if not ok:
        show_err(st, resp)
        sys.exit(1)
    print(json.dumps(resp.get("body"), ensure_ascii=False, indent=2)[:6000])


def cmd_draft(args):
    body = {}
    if args.card:
        body.update(load_card(args.card))
    wn_path = args.whats_new or DEFAULT_WHATS_NEW
    if "whatsNew" not in body:
        if not os.path.isfile(wn_path):
            die("нет файла whatsNew: %s" % wn_path)
        body["whatsNew"] = read_text(wn_path)
    if "moderInfo" not in body:
        body["moderInfo"] = read_moder(args.moder_file or DEFAULT_MODER_FILE)
    check_len("whatsNew", body["whatsNew"], LIM_WHATS_NEW)
    check_len("moderInfo", body["moderInfo"], LIM_MODER)
    path = "/public/v1/application/%s/version" % args.package
    print("POST %s поля: %s" % (path, ", ".join(sorted(body))))
    print("ВНИМАНИЕ: создание нового черновика через API удаляет существующий черновик;"
          " API создаёт черновик только при наличии активной версии.")
    if not args.yes:
        print("[dry-run] без --yes ничего не отправлено")
        return
    token = get_token()
    ok, st, resp = api("POST", path, token, json_body=body)
    if not ok:
        show_err(st, resp)
        sys.exit(1)
    print("Черновик создан: versionId=%s" % resp.get("body"))


def cmd_edit(args):
    body = load_card(args.card)
    if "moderInfo" in body:
        check_len("moderInfo", body["moderInfo"], LIM_MODER)
    if "whatsNew" in body:
        check_len("whatsNew", body["whatsNew"], LIM_WHATS_NEW)
    print("PATCH /public/v2/application/%s/version/<draft> поля: %s" % (args.package, ", ".join(sorted(body))))
    if not args.yes:
        print("[dry-run] без --yes ничего не отправлено")
        return
    token = get_token()
    vid = resolve_version(args, token)
    ok, st, resp = api("PATCH", "/public/v2/application/%s/version/%s" % (args.package, vid), token, json_body=body)
    if not ok:
        show_err(st, resp)
        sys.exit(1)
    print("Черновик %s обновлён" % vid)


def cmd_upload_screens(args):
    folder = args.path
    if not os.path.isdir(folder):
        die("нет папки %s" % folder)
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith((".png", ".jpg", ".jpeg")))
    if len(files) < 3:
        die("нужно минимум 3 скриншота, найдено %d" % len(files))
    if len(files) > 10:
        die("максимум 10 скриншотов (ordinal 0..9), найдено %d" % len(files))
    plan = []
    for i, f in enumerate(files):
        p = os.path.join(folder, f)
        kind, w, h = image_size(p)
        size = os.path.getsize(p)
        problems = []
        if not kind:
            problems.append("не png/jpg")
        if size > SCREEN_MAX_BYTES:
            problems.append("> 5 МБ")
        if not (320 <= min(w, h) and max(w, h) <= 3840):
            problems.append("стороны вне 320..3840")
        if w >= h:
            problems.append("не портрет")
        elif abs(w / h - 9 / 16) > 0.01:
            problems.append("не 9:16 (RuStore выдаст предупреждение)")
        print("  ordinal %d: %s %dx%d %.1f КБ %s" % (i, f, w, h, size / 1024, "; ".join(problems) or "ok"))
        if any(x for x in problems if not x.startswith("не 9:16")):
            die("скриншот %s не проходит требования" % f)
        plan.append((i, p))
    print("POST /public/v2/application/%s/version/<draft>/image/screenshot/PORTRAIT/{0..%d}/SCREENSHOT"
          % (args.package, len(plan) - 1))
    if not args.yes:
        print("[dry-run] без --yes ничего не отправлено")
        return
    token = get_token()
    vid = resolve_version(args, token)
    for i, p in plan:
        with open(p, "rb") as f:
            content = f.read()
        ok, st, resp = api("POST", "/public/v2/application/%s/version/%s/image/screenshot/PORTRAIT/%d/SCREENSHOT"
                           % (args.package, vid, i), token,
                           files={"file": (os.path.basename(p), content, ctype_for(p))})
        print("  %d %s: %s" % (i, os.path.basename(p), "OK" if ok else "FAIL"))
        if not ok:
            show_err(st, resp)
            sys.exit(1)


def cmd_upload_icon(args):
    p = args.path
    if not os.path.isfile(p):
        die("нет файла %s" % p)
    kind, w, h = image_size(p)
    size = os.path.getsize(p)
    print("  иконка: %s %dx%d %.1f КБ" % (kind, w, h, size / 1024))
    if not kind or (w, h) != (512, 512) or size > ICON_MAX_BYTES:
        die("иконка должна быть png/jpg 512×512, ≤ 3 МБ, без прозрачности по контуру")
    print("POST /public/v1/application/%s/version/<draft>/image/icon" % args.package)
    if not args.yes:
        print("[dry-run] без --yes ничего не отправлено")
        return
    token = get_token()
    vid = resolve_version(args, token)
    with open(p, "rb") as f:
        content = f.read()
    ok, st, resp = api("POST", "/public/v1/application/%s/version/%s/image/icon" % (args.package, vid), token,
                       files={"file": (os.path.basename(p), content, ctype_for(p))})
    print("Иконка: %s" % ("OK" if ok else "FAIL"))
    if not ok:
        show_err(st, resp)
        sys.exit(1)


def _upload_pkg(args, ext, path_tpl):
    p = args.path
    if not os.path.isfile(p) or not p.lower().endswith(ext):
        die("нужен файл %s: %s" % (ext, p))
    size = os.path.getsize(p)
    if size > PKG_MAX_BYTES:
        die("файл > 5 ГБ")
    path_shown = path_tpl % (args.package, "<draft>")
    print("POST %s  (%s, %.1f МБ)" % (path_shown, os.path.basename(p), size / 1024 / 1024))
    if not args.yes:
        print("[dry-run] без --yes ничего не отправлено")
        return
    token = get_token()
    vid = resolve_version(args, token)
    with open(p, "rb") as f:
        content = f.read()
    ok, st, resp = api("POST", path_tpl % (args.package, vid), token,
                       files={"file": (os.path.basename(p), content, ctype_for(p))}, timeout=900)
    print("Загрузка: %s" % ("OK" if ok else "FAIL"))
    if not ok:
        show_err(st, resp)
        sys.exit(1)


def cmd_upload_apk(args):
    _upload_pkg(args, ".apk", "/public/v1/application/%s/version/%s/apk?isMainApk=true")


def cmd_upload_aab(args):
    print("Напоминание: перед AAB нужно загрузить подпись приложения (PEPK) в RuStore Консоли.")
    _upload_pkg(args, ".aab", "/public/v1/application/%s/version/%s/aab")


def cmd_commit(args):
    print("POST /public/v1/application/%s/version/<draft>/commit — ОТПРАВКА НА МОДЕРАЦИЮ" % args.package)
    if not args.yes:
        print("[dry-run] без --yes ничего не отправлено")
        return
    token = get_token()
    vid = resolve_version(args, token)
    ok, st, resp = api("POST", "/public/v1/application/%s/version/%s/commit" % (args.package, vid), token)
    print("Commit: %s" % ("OK, отправлено на модерацию" if ok else "FAIL"))
    if not ok:
        show_err(st, resp)
        sys.exit(1)


def cmd_delete_draft(args):
    print("DELETE /public/v1/application/%s/version/<draft>" % args.package)
    if not args.yes:
        print("[dry-run] без --yes ничего не отправлено")
        return
    token = get_token()
    vid = resolve_version(args, token)
    ok, st, resp = api("DELETE", "/public/v1/application/%s/version/%s" % (args.package, vid), token)
    print("Удаление: %s" % ("OK" if ok else "FAIL"))
    if not ok:
        show_err(st, resp)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="RuStore Public API: публикация %s" % PACKAGE)
    ap.add_argument("--package", default=PACKAGE)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, path=False, write=False, version=False):
        p = sub.add_parser(name)
        if path:
            p.add_argument("path")
        if write:
            p.add_argument("--yes", action="store_true", help="реально выполнить запрос")
        if version:
            p.add_argument("--version-id", type=int)
        p.set_defaults(fn=fn)
        return p

    add("auth", cmd_auth)
    add("apps", cmd_apps)
    add("status", cmd_status)
    add("version-detail", cmd_version_detail, version=True)
    d = add("draft", cmd_draft, write=True)
    d.add_argument("--card", help="JSON с полями карточки (appName, shortDescription, fullDescription, ...)")
    d.add_argument("--whats-new", help="файл whatsNew (по умолчанию rustore/whats-new.txt)")
    d.add_argument("--moder-file", help="файл с комментарием модератору (строка 'moderInfo: ...')")
    e = add("edit", cmd_edit, write=True, version=True)
    e.add_argument("--card", required=True)
    add("upload-screens", cmd_upload_screens, path=True, write=True, version=True)
    add("upload-icon", cmd_upload_icon, path=True, write=True, version=True)
    add("upload-apk", cmd_upload_apk, path=True, write=True, version=True)
    add("upload-aab", cmd_upload_aab, path=True, write=True, version=True)
    add("commit", cmd_commit, write=True, version=True)
    add("delete-draft", cmd_delete_draft, write=True, version=True)

    args = ap.parse_args()
    for attr in ("yes", "version_id"):
        if not hasattr(args, attr):
            setattr(args, attr, None)
    args.fn(args)


if __name__ == "__main__":
    main()
