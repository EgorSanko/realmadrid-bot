#!/bin/bash
# ===========================================
# Real Madrid Bot - Deploy Script
# ===========================================

set -e

echo "🚀 Real Madrid Bot - Deployment"
echo "================================"

# Проверяем наличие .env
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден!"
    echo "   Скопируй .env.example в .env и заполни значения:"
    echo "   cp .env.example .env"
    echo "   nano .env"
    exit 1
fi

# Проверяем наличие credentials.json
if [ ! -f "credentials.json" ]; then
    echo "❌ Файл credentials.json не найден!"
    echo "   Скопируй файл Google Service Account"
    exit 1
fi

# Проверяем Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker не установлен!"
    echo "   curl -fsSL https://get.docker.com | sh"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose не установлен!"
    exit 1
fi

# Создаём директорию для данных
mkdir -p data

# Останавливаем старые контейнеры
echo "🛑 Останавливаем старые контейнеры..."
docker-compose down 2>/dev/null || true

# Собираем и запускаем
echo "🔨 Собираем образы..."
docker-compose build --no-cache

echo "🚀 Запускаем контейнеры..."
docker-compose up -d

# Проверяем статус
echo ""
echo "📊 Статус контейнеров:"
docker-compose ps

# Ждём запуска API
echo ""
echo "⏳ Ожидаем запуска API..."
sleep 5

# Проверяем health
if curl -s http://localhost:8000/api/health | grep -q "ok"; then
    echo "✅ API работает!"
else
    echo "⚠️ API не отвечает, проверь логи: docker-compose logs api"
fi

echo ""
echo "================================"
echo "✅ Деплой завершён!"
echo ""
echo "Полезные команды:"
echo "  docker-compose logs -f        # Логи"
echo "  docker-compose logs -f bot    # Логи бота"
echo "  docker-compose logs -f api    # Логи API"
echo "  docker-compose restart        # Перезапуск"
echo "  docker-compose down           # Остановка"
echo ""
echo "¡Hala Madrid! ⚪"
