
import os
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Response, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from starlette.middleware.sessions import SessionMiddleware

# =================== CONFIG ===================
WB_TOKEN = os.environ.get("WB_TOKEN")  # <-- ОБЯЗАТЕЛЬНО: установить в окружении (не хранить в Git)
if not WB_TOKEN:
    raise RuntimeError("Переменная окружения WB_TOKEN не установлена. Установи её перед запуском.")

AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "ilgar426A")  # пароль входа на сайт
REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "10"))
SESSION_SECRET = os.environ.get("SESSION_SECRET", "202071123d0cf3638cf3ab5cd58daefb")  # секрет для cookie-сессий

# Базовые URL Wildberries (могут меняться со временем; при необходимости поправь)
BASE_SUPPLIERS = "https://suppliers-api.wildberries.ru"
BASE_STATS = "https://statistics-api.wildberries.ru"

# =================== APP ===================
app = FastAPI(title="SIMHUB · WB MiniSite")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# Маппинг артикулов (код → nmId/фото/название)
ARTICLES = [
  {"code":"Y299.","wb_id":"300568253","image":"https://basket-18.wbbasket.ru/vol3005/part300568/300568253/images/big/1.webp","name":"Сим карта безлимитный интернет для телефона"},
  {"code":"Y810.","wb_id":"300618359","image":"https://basket-18.wbbasket.ru/vol3006/part300618/300618359/images/big/1.webp","name":"Сим карта безлимитный интернет с ограничением"},
  {"code":"B499.","wb_id":"300618360","image":"https://basket-18.wbbasket.ru/vol3006/part300618/300618360/images/big/1.webp","name":"Сим карта безлимитный интернет для всех устройств"},
  {"code":"B10.","wb_id":"300618361","image":"https://basket-18.wbbasket.ru/vol3006/part300618/300618361/images/big/1.webp","name":"Сим карта безлимитный интернет с ограничением"},
  {"code":"B1050.","wb_id":"300618363","image":"https://basket-18.wbbasket.ru/vol3006/part300618/300618363/images/big/1.webp","name":"Сим карта 1000Гб"},
  {"code":"МТС100.","wb_id":"300618366","image":"https://basket-18.wbbasket.ru/vol3006/part300618/300618366/images/big/1.webp","name":"Сим карта МТС 100Гб"},
  {"code":"M630.","wb_id":"300618367","image":"https://basket-18.wbbasket.ru/vol3006/part300618/300618367/images/big/1.webp","name":"Сим карта безлимитный интернет с ограничением"},
  {"code":"T700.","wb_id":"300619906","image":"https://basket-18.wbbasket.ru/vol3006/part300619/300619906/images/big/1.webp","name":"Сим карта Tele2 700"},
  {"code":"B135.","wb_id":"300825544","image":"https://basket-19.wbbasket.ru/vol3008/part300825/300825544/images/big/1.webp","name":"Сим карта безлимит 135"},
  {"code":"Y600.","wb_id":"328123226","image":"https://basket-20.wbbasket.ru/vol3281/part328123/328123226/images/big/1.webp","name":"Сим карта безлимитный интернет с ограничением"},
  {"code":"2B499.","wb_id":"384399653","image":"https://basket-22.wbbasket.ru/vol3843/part384399/384399653/images/big/1.webp","name":"Сим карта 1000Гб для всех устройств"},
  {"code":"M45.","wb_id":"432671801","image":"https://basket-24.wbbasket.ru/vol4326/part432671/432671801/images/big/1.webp","name":"Сим карта безлимитный интернет с ограничением"},
  {"code":"M30.","wb_id":"432671802","image":"https://basket-24.wbbasket.ru/vol4326/part432671/432671802/images/big/1.webp","name":"Сим карта безлимитный интернет с ограничением"}
]

# Кэш
CACHE: Dict[str, Any] = {"by_code": {}, "updated_at": None}

# =================== HELPERS ===================
async def wb_get(client: httpx.AsyncClient, url: str, params: dict = None):
    headers = {"Authorization": WB_TOKEN}
    r = await client.get(url, headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        # Возвращаем None, чтобы не падать из-за временных ошибок WB
        return None
    try:
        return r.json()
    except Exception:
        return None

async def pull_orders_30days():
    """Получаем заказы за 30 дней, агрегируем по nmId/supplierArticle.
       Возвращаем словарь: key -> {"daily": {YYYY-MM-DD: qty}, "totalQty30": int, "revenue30": float}"""
    date_from = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
    url = f"{BASE_SUPPLIERS}/api/v3/orders"
    out = {}
    async with httpx.AsyncClient() as client:
        # WB обычно требует пагинацию: используем take/skip, пока не закончится
        take = 1000
        skip = 0
        while True:
            params = {"dateFrom": date_from, "take": take, "skip": skip}
            resp = await wb_get(client, url, params)
            if not resp:
                break
            rows = resp.get("orders") or resp.get("data") or resp
            if not isinstance(rows, list) or len(rows) == 0:
                break
            for row in rows:
                # Идентификатор артикула
                key = str(row.get("supplierArticle") or row.get("article") or row.get("supplierArticleId") or row.get("nmId") or "")
                if not key:
                    continue
                # количество и цена
                qty = int(row.get("quantity", 1) or 1)
                price = float(row.get("totalPrice") or row.get("price") or 0)
                # дата
                dstr = (row.get("createdAt") or row.get("dateCreate") or row.get("date") or "")[:10]
                if not dstr:
                    dstr = datetime.utcnow().date().isoformat()
                # аккумулируем
                group = out.setdefault(key, {"daily": {}, "totalQty30": 0, "revenue30": 0.0})
                group["daily"][dstr] = group["daily"].get(dstr, 0) + qty
                group["totalQty30"] += qty
                group["revenue30"] += price
            # следующая страница
            if len(rows) < take:
                break
            skip += take
    return out

async def pull_stocks():
    """Остатки по складам. Возвращаем словарь: key -> [{"warehouse": str, "qty": int}, ...]"""
    url = f"{BASE_STATS}/api/v1/supplier/stocks"
    result = {}
    async with httpx.AsyncClient() as client:
        resp = await wb_get(client, url)
        rows = (resp.get("data") or resp.get("stocks") or resp.get("rows") or resp) if resp else []
        if not isinstance(rows, list):
            return {}
        for r in rows:
            key = str(r.get("supplierArticle") or r.get("supplierArticleId") or r.get("nmId") or "")
            if not key:
                continue
            stocks_list = []
            if isinstance(r.get("stocks"), list):
                for s in r.get("stocks"):
                    name = s.get("warehouseName") or s.get("warehouse") or s.get("whName") or "Склад"
                    qty = int(s.get("quantity") or s.get("qty") or 0)
                    stocks_list.append({"warehouse": name, "qty": qty})
            else:
                qty = int(r.get("quantity") or 0)
                stocks_list.append({"warehouse": "Склад", "qty": qty})
            result[key] = stocks_list
    return result

async def pull_supplies():
    """Список поставок (на будущее/для раздела Поставки)."""
    url = f"{BASE_SUPPLIERS}/api/v3/supplies"
    async with httpx.AsyncClient() as client:
        resp = await wb_get(client, url)
        if not resp:
            return []
        return resp.get("supplies") or resp.get("data") or resp

async def refresh_all():
    try:
        orders_map = await pull_orders_30days()
        stocks_map = await pull_stocks()
        _ = await pull_supplies()  # пока не используем, но полезно иметь кеш
    except Exception as e:
        print("Ошибка обновления:", e)
        orders_map, stocks_map = {}, {}

    by_code = {}
    for a in ARTICLES:
        code = a["code"]
        wb_id = a["wb_id"]
        # WB по разному выдает ключи: пробуем по nmId и по code
        om = orders_map.get(wb_id) or orders_map.get(code) or {}
        daily_dict = om.get("daily", {})
        daily_list = []
        for i in range(30, 0, -1):
            d = (datetime.utcnow().date() - timedelta(days=i-1)).isoformat()
            daily_list.append(int(daily_dict.get(d, 0)))
        totalQty30 = int(om.get("totalQty30", 0))
        revenue30 = float(om.get("revenue30", 0.0))

        sm = stocks_map.get(wb_id) or stocks_map.get(code) or []

        by_code[code] = {
            "code": code,
            "wb_id": wb_id,
            "name": a.get("name"),
            "image": a.get("image"),
            "dailyOrders": daily_list,
            "totalQty30": totalQty30,
            "revenue30": int(revenue30),
            "stocks": sm
        }

    CACHE["by_code"] = by_code
    CACHE["updated_at"] = datetime.utcnow().isoformat() + "Z"
    print("REFRESHED:", CACHE["updated_at"])

# =================== AUTH (simple password) ===================
LOGIN_HTML = """
<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Вход</title>
<style>
body{background:#0b0d12;color:#e9eef8;font-family:system-ui;margin:0;padding:40px}
form{max-width:420px;margin:80px auto;background:#0f1320;padding:24px;border-radius:12px;border:1px solid #1e2530;box-shadow:0 10px 30px rgba(0,0,0,.35)}
input{width:100%;padding:12px;margin:10px 0;border-radius:8px;border:1px solid #222a35;background:#0b1119;color:#fff}
button{padding:12px 16px;border-radius:8px;background:#2a6bff;border:0;color:#fff;font-weight:600;cursor:pointer}
.err{color:#ff6b7d;margin:0 0 6px 0}
</style></head>
<body>
  <form method="post" action="/login">
    <h2>Защищённый вход</h2>
    <p>Введите пароль для доступа к дашборду.</p>
    {error}
    <input name="password" type="password" placeholder="Пароль" autofocus>
    <button type="submit">Войти</button>
  </form>
</body></html>
"""

def is_authed(request: Request) -> bool:
    return bool(request.session.get("auth"))

@app.get("/login")
def login_get():
    return HTMLResponse(LOGIN_HTML.format(error=""))

@app.post("/login")
async def login_post(request: Request, password: str = Form(...)):
    if password == AUTH_PASSWORD:
        request.session["auth"] = True
        return RedirectResponse(url="/", status_code=302)
    html = LOGIN_HTML.format(error="<p class='err'>Неверный пароль</p>")
    return HTMLResponse(html, status_code=401)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)

# =================== MIDDLEWARE (protect) ===================
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Разрешаем публично только страницы логина и статику (favicon тоже)
    if path.startswith("/login") or path.startswith("/static") or path == "/favicon.ico":
        return await call_next(request)
    # API summary и главную страницу защищаем
    if not is_authed(request):
        # API: вернуть 401 JSON
        if path.startswith("/summary"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        # HTML: редирект на логин
        return RedirectResponse(url="/login")
    return await call_next(request)

# =================== ROUTES ===================
# Раздача статики
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def index():
    # отдадим статический index.html
    path = os.path.join("static", "index.html")
    if not os.path.exists(path):
        return HTMLResponse("<h3>Файл static/index.html не найден</h3>", status_code=500)
    return FileResponse(path, media_type="text/html")

@app.get("/summary")
async def summary(codes: str = ""):
    # возвращаем агрегат по запрошенным кодам
    if not CACHE.get("by_code"):
        return JSONResponse([], status_code=200)
    wanted = [c for c in (codes.split(",") if codes else [])]
    out = []
    for c in wanted:
        item = CACHE["by_code"].get(c)
        if item:
            out.append(item)
    return JSONResponse(out)

@app.get("/health")
def health():
    return {"status":"ok","updated_at":CACHE.get("updated_at")}

# =================== STARTUP (scheduler) ===================
@app.on_event("startup")
async def startup_event():
    await refresh_all()
    sch = AsyncIOScheduler()
    sch.add_job(lambda: asyncio.create_task(refresh_all()), "interval", minutes=REFRESH_MINUTES, id="wb-refresh")
    sch.start()
