# SIMHUB · WB MiniSite (FastAPI)
Готовый автономный сайт-панель по артикулам Wildberries.

## Что внутри
- FastAPI сервер (`app.py`) — опрашивает WB каждые 10 минут, кеширует и отдаёт агрегат `/summary`.
- Защита паролем (форма логина). Пароль по умолчанию `ilgar426A` (можно задать через `AUTH_PASSWORD`).
- Тёмный фронтенд (`static/index.html`) — 13 карточек (3 в ряд): фото, график заказов за 30 дней, выручка, остатки по складам, прогноз дней до нуля.
- Dockerfile и requirements.

## Быстрый старт (локально)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export WB_TOKEN="ВАШ_WB_TOKEN"           # ОБЯЗАТЕЛЬНО
export AUTH_PASSWORD="ilgar426A"         # опционально
export SESSION_SECRET="случайная_строка" # опционально
export REFRESH_MINUTES=10                # опционально

uvicorn app:app --reload
# Открыть http://127.0.0.1:8000 → ввести пароль
```

## Docker
```bash
docker build -t simhub-wb .
docker run -d -p 8000:8000   -e WB_TOKEN="ВАШ_WB_TOKEN"   -e AUTH_PASSWORD="ilgar426A"   -e SESSION_SECRET="случайная_строка"   -e REFRESH_MINUTES=10   simhub-wb
```

## Примечания
- Токен WB храните только в переменных окружения, не коммитьте в Git.
- Если WB вернёт нестандартный формат ответов, возможно, потребуется маленькая правка парсинга.
- Эндпоинты WB в коде могут отличаться в будущих версиях WB API.
