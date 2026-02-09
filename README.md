# ⚽ Real Madrid Fan Bot

<div align="center">

![Real Madrid](https://images.fotmob.com/image_resources/logo/teamlogo/8633.png)

**Telegram Mini App для фанатов Реал Мадрид**

Ставки · Прогнозы · Live-матчи · Мини-игры · Новости

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react)](https://react.dev)
[![Telegram](https://img.shields.io/badge/Telegram-Mini_App-26A5E4?logo=telegram)](https://core.telegram.org/bots/webapps)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)](https://docker.com)

</div>

---

## 📋 О проекте

Полнофункциональное Telegram Mini App приложение для фанатов Real Madrid. Пользователи зарабатывают очки через прогнозы, ставки на матчи и мини-игры, после чего могут обменять их на реальные призы.

### Основные фичи

- **🏟️ Матчи** — расписание, результаты, составы, статистика и карта ударов в реальном времени
- **📺 Live** — отслеживание матчей в реальном времени с моментумом, событиями и картой ударов
- **💰 Ставки** — pre-match и live ставки с реальными коэффициентами от Leon
- **🔮 Прогнозы** — бесплатные прогнозы на каждый матч
- **🎮 Мини-игры** — Пенальти, Memory, Ну, погоди! (Электроника-стиль), Викторина
- **📰 Новости** — автоматический парсинг из Telegram-каналов RM с фото и видео
- **🏆 Рейтинг** — лидерборд с Telegram-аватарками
- **📊 Таблица** — La Liga standings с логотипами команд
- **🎬 Хайлайты** — встроенный YouTube плеер прямо в приложении
- **🎁 Магазин призов** — обмен очков на Telegram Premium, футболки и т.д.

---

## 🏗️ Архитектура

```
┌──────────────────────────────────────────────────────┐
│                  Telegram Mini App                    │
│                   (index.html)                        │
│         React 18 + Tailwind CSS + Babel               │
├──────────────────────────────────────────────────────┤
│                    FastAPI Backend                     │
│                     (api.py)                           │
│         5000+ строк · 40+ эндпоинтов                  │
├────────┬────────┬────────┬────────┬──────────────────┤
│ FotMob │ Leon   │SofaSc. │ Google │ Telegram         │
│  API   │  API   │  API   │Sheets  │ Bot API          │
│        │        │        │        │ + Telethon       │
├────────┴────────┴────────┴────────┴──────────────────┤
│              SQLite (database.py)                     │
│       Пользователи · Ставки · Прогнозы · Игры        │
└──────────────────────────────────────────────────────┘
```

### Технологический стек

| Компонент | Технология |
|-----------|------------|
| **Frontend** | React 18, Tailwind CSS, Babel (standalone, single-file SPA) |
| **Backend** | Python 3.11+, FastAPI, Uvicorn |
| **Database** | SQLite3 |
| **APIs** | FotMob, SofaScore, Leon, YouTube, Telegram Bot API, VK API, Telethon |
| **Deploy** | Docker Compose, Nginx (reverse proxy) |
| **Мини-игры** | Vanilla JS + Canvas (отдельные HTML файлы) |

---

## 📂 Структура проекта

```
realmadrid-bot/
├── api.py                 # FastAPI бэкенд (5000+ строк)
│                          # - 40+ REST эндпоинтов  
│                          # - FotMob/SofaScore/Leon парсеры
│                          # - Live матчи, ставки, прогнозы
│                          # - Telegram авторизация (WebApp)
│                          # - Новости из TG каналов (Telethon)
│                          # - Система квизов с GPT-генерацией
│                          # - Автоматический расчёт ставок
│
├── bot.py                 # Telegram бот (python-telegram-bot)
│                          # - Команды: /start, /admin
│                          # - Уведомления о матчах (5ч и 5мин)
│                          # - Рассылка результатов
│                          # - Google Sheets интеграция
│
├── index.html             # Главный SPA фронтенд (4500+ строк)
│                          # - React 18 + Tailwind + Babel
│                          # - 6 табов: Главная, Матчи, Ставки, 
│                          #   Игры, Новости, Профиль
│                          # - FotMob-стиль дизайн
│                          # - Telegram WebApp SDK
│
├── penalty.html           # 🎮 Мини-игра "Пенальти"
│                          # - Canvas-based, swipe для удара
│                          # - 3 сложности, анимации
│
├── memory.html            # 🧠 Мини-игра "Memory"  
│                          # - Найди пары игроков RM
│                          # - Таймер, комбо-множитель
│
├── nu-pogodi.html         # 🐔 Мини-игра "Ну, погоди!"
│                          # - Электроника-стиль
│                          # - Вини ловит мячи на 4 позициях
│
├── database.py            # SQLite ORM
│                          # - users, bets, predictions, games
│                          # - CRUD операции, лидерборд
│
├── google_sheets.py       # Google Sheets клиент
│                          # - Расписание матчей, результаты
│                          # - Коэффициенты
│
├── config.py              # Конфигурация
│                          # - Environment variables
│
├── Dockerfile             # Python 3.11-slim контейнер
├── docker-compose.yml     # Оркестрация сервисов
├── requirements.txt       # Python зависимости
├── .env                   # Секреты (не в репозитории!)
└── .env.example           # Шаблон переменных окружения
```

---

## 🔌 API Endpoints

### Пользователи
| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/user/me` | Текущий пользователь |
| `GET` | `/api/user/bets` | Ставки пользователя |
| `GET` | `/api/user/predictions` | Прогнозы пользователя |
| `GET` | `/api/user/transactions` | История транзакций |
| `GET` | `/api/avatar/{user_id}` | Telegram аватарка |

### Матчи
| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/bundle` | Все данные за 1 запрос (оптимизация) |
| `GET` | `/api/match/next` | Следующий матч + коэффициенты |
| `GET` | `/api/matches/upcoming` | Расписание (FotMob) |
| `GET` | `/api/matches/results` | Результаты с логотипами |
| `GET` | `/api/match/details/{id}` | Детали: составы, xG, shotmap, события |
| `GET` | `/api/match/analytics` | AI-аналитика матча |
| `GET` | `/api/standings` | Таблица La Liga |
| `GET` | `/api/live` | Live матч: счёт, события, моментум |

### Ставки и прогнозы
| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/api/bet/place` | Сделать pre-match ставку |
| `POST` | `/api/bet/live` | Live ставка с актуальными коэфами |
| `POST` | `/api/bet/sell` | Продать ставку (cashout) |
| `POST` | `/api/prediction/make` | Бесплатный прогноз |
| `GET` | `/api/odds` | Текущие коэффициенты (Leon) |

### Игры
| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/quiz/question` | Вопрос викторины |
| `POST` | `/api/quiz/answer` | Ответ на викторину |
| `POST` | `/api/games/result` | Результат мини-игры |
| `GET` | `/api/games/status` | Статус доступных игр |

### Прочее
| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/news` | Новости из Telegram каналов |
| `GET` | `/api/leaderboard` | Рейтинг с аватарками |
| `GET` | `/api/players` | Состав Real Madrid |
| `GET` | `/api/prizes` | Доступные призы |
| `POST` | `/api/prize/claim` | Запросить приз |
| `GET` | `/api/health` | Проверка работоспособности |

---

## 🚀 Запуск

### Требования

- Docker + Docker Compose
- Telegram Bot ([@BotFather](https://t.me/BotFather))
- Домен с SSL (для Telegram WebApp)

### 1. Клонировать

```bash
git clone https://github.com/EgorSanko/realmadrid-bot.git
cd realmadrid-bot
```

### 2. Настроить окружение

```bash
cp .env.example .env
nano .env  # Заполнить все переменные
```

### 3. Запустить

```bash
docker-compose up -d --build
```

### 4. Настроить бота

В [@BotFather](https://t.me/BotFather):
1. `/mybots` → выбрать бота → **Bot Settings** → **Menu Button**
2. Указать URL вашего WebApp: `https://yourdomain.com`

---

## ⚙️ Переменные окружения

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `TELEGRAM_TOKEN` | Токен бота от BotFather | `123456:ABC-...` |
| `TG_API_ID` | Telegram API ID (my.telegram.org) | `12345678` |
| `TG_API_HASH` | Telegram API Hash | `abc123...` |
| `VK_SERVICE_KEY` | VK API ключ (для доп. данных) | `abc123...` |
| `WEBAPP_URL` | URL WebApp | `https://yourdomain.com` |
| `SPREADSHEET_ID` | ID Google Таблицы | `1abc...xyz` |
| `ADMIN_IDS` | Telegram ID администраторов | `123456,789012` |

---

## 📊 Источники данных

### FotMob (основной)
- Расписание и результаты матчей
- Составы с позициями на поле
- Статистика матчей (владение, удары, xG)
- Карта ударов (shotmap)
- Рейтинги игроков
- Таблица La Liga с логотипами
- Детекция live-матчей

### Leon
- Коэффициенты для ставок (pre-match + live)
- Маркеты: 1X2, точный счёт, тоталы
- Обновление в реальном времени

### SofaScore (fallback)
- Резервный источник для матчей
- События и составы

### YouTube
- Хайлайты с официального канала @realmadrid
- Встроенный плеер (embed)

### Telegram (Telethon)
- Парсинг новостей из каналов RM
- Фото и видео контент
- Аватарки пользователей через Bot API

---

## 🎮 Мини-игры

### ⚽ Пенальти
Canvas-based игра с swipe-управлением. 5 ударов, 3 уровня сложности. Вратарь с AI прыгает на основе сложности.

### 🧠 Memory
Карточная игра — найди пары с фото игроков Real Madrid. Таймер, комбо-множитель за подряд угаданные пары.

### 🐔 Ну, погоди!
Ремейк советской электроники "Ну, погоди!". Вини Джуниор ловит мячи на 4 позициях. Нарастающая скорость, жизни.

### 🧠 Викторина
Вопросы о Real Madrid с GPT-генерацией. 3 сложности, таймер на ответ. Очки за правильные ответы.

---

## 🔧 Оптимизации

### Bundle API
Один запрос `/api/bundle` вместо 8 отдельных. Параллельное выполнение через `ThreadPoolExecutor` (6 потоков). Начальная загрузка: **7с → 3.7с** (-47%).

### 2-стадийная загрузка
- **Stage 1** (< 1с): пользователь, ставки, лидерборд (DB/cache)
- **Stage 2** (фон): матчи, результаты, таблица (внешние API)
- **Отдельно**: новости (самые медленные)

### Кэширование
- FotMob данные: TTL 5-15 мин
- Leon коэффициенты: TTL 30с
- YouTube хайлайты: TTL 1ч
- Telegram аватарки: локальное хранение, обновление 24ч

### Фронтенд
- Preconnect к CDN (`images.fotmob.com`)
- Lazy loading для изображений
- Скелетон-лоадеры для UX
- Tabular-nums для выравнивания цифр

---

## 📱 Скриншоты

<details>
<summary>Раскрыть скриншоты</summary>

| Главная | Матчи | Live |
|---------|-------|------|
| Следующий матч, коэффициенты, быстрые ставки | Расписание, результаты с лого, таблица | Счёт, события, моментум, shotmap |

| Детали матча | Ставки | Рейтинг |
|-------------|--------|---------|
| Составы на поле, статистика, xG | Pre-match и live ставки | Лидерборд с аватарками |

</details>

---

## 🤝 Contributing

Pull requests приветствуются! Для крупных изменений сначала создайте issue.

---

## 📝 Лицензия

MIT License — свободное использование с указанием авторства.

---

## 👤 Автор

**Egor Sanko** — [@EgorSanko](https://github.com/EgorSanko)

---

<div align="center">
<sub>Hala Madrid y nada más! 🤍</sub>
</div>
