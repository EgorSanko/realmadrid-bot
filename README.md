<div align="center">

<img src="docs/readme/banner.png" alt="Мадридиста — фан-приложение мадридского «Реала»" width="100%">

<h3>Всё о «Реале» — в одном приложении</h3>

<p>
  <a href="https://realmadridfan.ru"><img src="https://img.shields.io/badge/сайт-realmadridfan.ru-C9A45C?style=for-the-badge&labelColor=0A1633" alt="Сайт"></a>
  <a href="https://t.me/Real_Madrid_football_bot"><img src="https://img.shields.io/badge/Telegram-Mini%20App-26A5E4?style=for-the-badge&logo=telegram&logoColor=white&labelColor=0A1633" alt="Telegram Mini App"></a>
  <img src="https://img.shields.io/badge/Android-RuStore-3DDC84?style=for-the-badge&logo=android&logoColor=white&labelColor=0A1633" alt="Android · RuStore">
</p>

<p>
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white&labelColor=0A1633" alt="React 19">
  <img src="https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white&labelColor=0A1633" alt="TypeScript">
  <img src="https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white&labelColor=0A1633" alt="Vite">
  <img src="https://img.shields.io/badge/FastAPI-Python-009688?logo=fastapi&logoColor=white&labelColor=0A1633" alt="FastAPI">
  <img src="https://img.shields.io/badge/SQLite-snapshots-003B57?logo=sqlite&logoColor=white&labelColor=0A1633" alt="SQLite">
  <img src="https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white&labelColor=0A1633" alt="Docker">
  <img src="https://img.shields.io/badge/Kotlin-WebView-7F52FF?logo=kotlin&logoColor=white&labelColor=0A1633" alt="Kotlin">
</p>

<sub>Неофициальное фан-приложение · не связано с Real Madrid C.F.</sub>

</div>

---

## ✨ Что внутри

| | |
|---|---|
| ⏱️ **Ближайший матч** | Отсчёт до стартового свистка, стадион, погода, судья со статистикой |
| 🔴 **Live** | Счёт и минута в реальном времени, хронология, плашка «ГОЛ!» с фото автора и конфетти, «Пропустили» на гол соперника |
| 📊 **Разбор матча** | 37 показателей статистики по таймам, xG, график давления, карта ударов, зоны атак |
| 👕 **Составы** | Расстановка на поле с оценками игроков, замены, кто не сыграет |
| 🗒️ **Онлайн** | Ключевые моменты по-русски и текстовая трансляция |
| 🏆 **Турниры** | Таблицы Ла Лиги и Лиги чемпионов, календарь, матчи тура |
| 🧑‍🤝‍🧑 **Игроки** | Профили, статистика сезона, последние матчи |
| 🎯 **Прогнозы** | Угадай счёт и автора гола, очки, общий рейтинг и лиги с друзьями |
| 📰 **Медиа** | Новости и видео прямо в приложении |
| 🎮 **Игры** | Викторина и «Пенальти» |

## 📱 Как выглядит

<table>
  <tr>
    <td align="center"><img src="docs/readme/home-top.png" width="190"><br><sub>Главная</sub></td>
    <td align="center"><img src="docs/readme/match.png" width="190"><br><sub>Матч</sub></td>
    <td align="center"><img src="docs/readme/lineups.png" width="190"><br><sub>Составы</sub></td>
    <td align="center"><img src="docs/readme/stats.png" width="190"><br><sub>Статистика</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/readme/online.png" width="190"><br><sub>Онлайн</sub></td>
    <td align="center"><img src="docs/readme/table.png" width="190"><br><sub>Таблица</sub></td>
    <td align="center"><img src="docs/readme/player.png" width="190"><br><sub>Игрок</sub></td>
    <td align="center"><img src="docs/readme/predict.png" width="190"><br><sub>Прогнозы</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/readme/media.png" width="190"><br><sub>Медиа</sub></td>
    <td align="center"><img src="docs/readme/games.png" width="190"><br><sub>Игры</sub></td>
    <td colspan="2" align="center"><img src="docs/readme/match-desktop.jpg" width="400"><br><sub>Сайт на компьютере</sub></td>
  </tr>
</table>

## 🏗️ Как устроено

```mermaid
flowchart LR
    subgraph Источники
      FM[FotMob]:::src
      SS[SofaScore]:::src
      ES[ESPN]:::src
      LS[LiveScore]:::src
      MD[RSS / YouTube]:::src
    end
    C[Сборщик<br/>app.collector]:::core
    DB[(SQLite<br/>снимки)]:::db
    API[API<br/>FastAPI]:::core
    W[Сайт + Telegram Mini App<br/>React 19]:::ui
    A[Android<br/>WebView]:::ui
    B[Telegram-бот<br/>вход по коду]:::ui
    FM --> C
    SS --> C
    ES --> C
    LS --> C
    MD --> C
    C --> DB --> API --> W
    API --> A
    C --- B
    classDef src fill:#0F1E42,stroke:#C9A45C,color:#E3C88B
    classDef core fill:#12224A,stroke:#C9A45C,color:#F6EBCB
    classDef db fill:#0A1633,stroke:#C9A45C,color:#F6EBCB
    classDef ui fill:#13234A,stroke:#26A5E4,color:#EEF0F5
```

- **Сборщик** опрашивает источники по расписанию: во время матча каждые 12 секунд, вне окна матча — реже. Для каждого вида данных — цепочка резервов **FotMob → SofaScore → ESPN → LiveScore**: упал один источник — данные берутся из следующего, а если упали все, API отдаёт последний удачный снимок с его возрастом.
- **API никогда не ходит во внешние источники** — только читает снимки из SQLite. Поэтому сайт отвечает быстро и не зависит от чужих сбоев.
- **Картинки** (эмблемы, фото игроков, логотипы турниров) идут через кэширующий прокси nginx с нашего домена — клиент не обращается к сторонним сайтам.
- **Прогнозы** — отдельная база: прогнозы, начисление очков после свистка, рейтинги по сезону и месяцу, лиги с приглашением по ссылке.
- **Вход** — Telegram Mini App (initData), на сайте — по одноразовому коду через бота.

## 🧰 Стек

| Часть | Технологии |
|---|---|
| Фронтенд | React 19, TypeScript, Vite, собственный UI-кит, Web Animations API |
| Бэкенд | Python, FastAPI, httpx, SQLite |
| Инфраструктура | Docker Compose (api + collector), nginx с кэшем картинок, автоматический деплой с проверкой `nginx -t` и откатом |
| Android | Kotlin, WebView-оболочка для RuStore |
| Качество | pytest (бэкенд), node:test (фронтенд), Playwright для визуальных проверок |

## 📂 Структура

```
backend/     API и сборщик данных (FastAPI, SQLite), тесты — backend/tests
frontend/    сайт и Telegram Mini App (React 19 + TypeScript + Vite), тесты — frontend/tests
android/     приложение для RuStore (Kotlin, WebView)
deploy/      деплой, nginx, бэкапы, watchdog
design/      макеты и дизайн-система
docs/        документация и картинки README
checks/      скриншоты визуальных проверок
```

## 🚀 Запуск локально

```bash
# бэкенд
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt
.venv/Scripts/python -m app.collector once team      # один цикл сбора данных команды
.venv/Scripts/uvicorn app.main:app --reload --port 8010
.venv/Scripts/python -m pytest -q                    # тесты

# фронтенд
cd frontend
npm install
npm run dev                                          # http://localhost:5173
npm test && npx tsc -b && npm run build              # тесты, типы, сборка
```

Боевой запуск — `docker compose up -d --build` (контейнеры `api` и `collector`), деплой — `bash deploy/deploy.sh`.
Секреты (`BOT_TOKEN` и др.) — только в `.env` на сервере, в репозиторий не попадают.

## 📜 Дисклеймер

«Мадридиста» — неофициальное фан-приложение, сделанное болельщиками. Проект не связан с Real Madrid C.F.,
LaLiga, UEFA и их партнёрами. Названия клубов, эмблемы и фотографии принадлежат их правообладателям и
используются для информирования. Данные о матчах — из открытых источников.

<div align="center"><sub>Сделано с ❤️ к «Реалу» · <a href="https://realmadridfan.ru">realmadridfan.ru</a></sub></div>
