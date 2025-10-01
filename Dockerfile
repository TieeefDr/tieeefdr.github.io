FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Раз в 10 минут обновление данных WB (можно менять в Render переменной окружения)
ENV REFRESH_MINUTES=10

# В Render веб-сервис должен слушать порт из переменной PORT.
# Запускаем через оболочку, чтобы подставился $PORT.
CMD bash -c 'uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}'
