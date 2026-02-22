# ⚪ Real Madrid Fan Bot v5.1

Telegram бот для фанатов Реал Мадрида с системой ставок, прогнозов и рейтингов.

## 🚀 Быстрый старт

### 1. Клонируй репозиторий
```bash
git clone <repo-url>
cd RealMadridBot
```

### 2. Настрой окружение
```bash
# Скопируй пример конфига
cp .env.example .env

# Отредактируй .env - заполни все значения!
nano .env
```

### 3. Добавь credentials.json
Скопируй файл `credentials.json` от Google Service Account в корень проекта.

⚠️ **ВАЖНО**: Никогда не коммить `.env` и `credentials.json` в git!

### 4. Запуск через Docker
```bash
# Сборка и запуск
docker-compose up -d --build

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

## 📁 Структура проекта

```
RealMadridBot/
├── bot.py              # Telegram бот (уведомления, команды)
├── api.py              # REST API для Web App
├── database.py         # SQLite база данных
├── config.py           # Единая конфигурация
├── google_sheets.py    # Работа с Google Sheets
├── player_stats.py     # Статистика игроков
├── liveball.py         # Ссылки на трансляции
├── index.html          # React Web App
│
├── Dockerfile          # Docker для бота
├── Dockerfile.api      # Docker для API
├── docker-compose.yml  # Оркестрация контейнеров
│
├── requirements.txt    # Python зависимости
├── .env.example        # Пример конфигурации
├── .gitignore          # Игнорируемые файлы
└── README.md           # Этот файл
```

## ⚙️ Конфигурация (.env)

```env
# Telegram
TELEGRAM_TOKEN=your_bot_token
BOT_USERNAME=YourBotName
ADMIN_IDS=123456789,987654321

# Google Sheets
SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_CREDENTIALS_FILE=/app/credentials.json

# Database
DATABASE_PATH=/app/data/betting.db

# Web App
WEBAPP_URL=https://your-domain.com
API_URL=http://localhost:8000
```

## 🔧 Функционал

### Бот (bot.py)
- `/start` - Регистрация и главное меню
- `/admin` - Админ-панель (статистика)
- `/settle` - Ручной расчёт ставок
- `/addbal @user 100` - Пополнить баланс

### Уведомления
- За 5 часов до матча
- За 5 минут с ссылкой на трансляцию
- Авто-расчёт завершённых матчей

### API (api.py)
- `GET /api/health` - Проверка работоспособности
- `GET /api/user/me` - Данные пользователя
- `GET /api/matches/upcoming` - Предстоящие матчи
- `POST /api/bet` - Сделать ставку
- `POST /api/prediction` - Сделать прогноз
- И многое другое...

### Web App (index.html)
- Просмотр матчей и результатов
- Ставки на коэффициенты
- Прогнозы на исход
- Викторина о Реал Мадрид
- Рейтинг пользователей
- Магазин призов

## 📊 Google Sheets

Таблица должна содержать листы:
- **Matches** - предстоящие матчи
- **Results** - результаты
- **Standings** - таблица La Liga
- **BetTypes** - коэффициенты

Google Apps Script для автообновления находится в `google_apps_script_v3.js`.

## 🛠 Разработка

### Локальный запуск
```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск бота
python bot.py

# Запуск API (в другом терминале)
uvicorn api:app --reload --port 8000
```

### Полезные команды Docker
```bash
# Пересборка одного сервиса
docker-compose up -d --build bot

# Вход в контейнер
docker exec -it rm-bot bash

# Просмотр логов API
docker-compose logs -f api

# Очистка
docker-compose down -v --rmi all
```

## 🔒 Безопасность

⚠️ **НИКОГДА не коммить:**
- `.env` файлы
- `credentials.json`
- `*.session` файлы (Telethon)
- Любые токены и ключи

Если секреты утекли:
1. Немедленно отзови все ключи
2. Создай новые токены
3. Обнови `.env` на сервере

## 🚀 Деплой на сервер

### 1. Подготовка сервера
```bash
# Установи Docker и Docker Compose
curl -fsSL https://get.docker.com | sh
apt install docker-compose

# Создай директорию
mkdir -p /opt/realmadrid-bot
cd /opt/realmadrid-bot
```

### 2. Загрузи файлы
```bash
# Через git
git clone <repo> .

# Или через scp
scp -r ./* user@server:/opt/realmadrid-bot/
```

### 3. Настрой окружение
```bash
cp .env.example .env
nano .env  # Заполни все значения

# Загрузи credentials.json
scp credentials.json user@server:/opt/realmadrid-bot/
```

### 4. Запусти
```bash
docker-compose up -d --build
docker-compose logs -f
```

### 5. Настрой Nginx (опционально)
```nginx
server {
    listen 80;
    server_name api.yourdomain.com;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 📝 Changelog

### v5.1 (Current)
- ✅ Исправлена SQL injection уязвимость
- ✅ Единая конфигурация (config.py)
- ✅ Исправлен двойной commit в database.py
- ✅ Разделены Docker образы для бота и API
- ✅ Добавлен health check
- ✅ Улучшено логирование

### v5.0
- Полный расчёт всех типов ставок
- Интеграция с SofaScore API
- Telegram Web App

## ¡Hala Madrid! ⚪
