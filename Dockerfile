FROM python:3.11-slim

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY *.py ./
COPY *.json ./

# Создаём директорию для данных
RUN mkdir -p /app/data

# Запуск бота
CMD ["python", "bot.py"]
