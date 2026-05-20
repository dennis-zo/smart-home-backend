from fastapi import FastAPI
from dotenv import load_dotenv

# חשוב לטעון לפני שאר הייבואים כדי שהמשתנים יהיו זמינים
load_dotenv()

from app.services.telegram_services import telegram_router, send_telegram_message
from app.services.devices_services import devices_router

app = FastAPI(title="Smart Home Core API")

app.include_router(telegram_router)
app.include_router(devices_router)

# שימוש ב-Lifecycle Event - קורה כשהשרת עולה
@app.on_event("startup")
async def on_startup():
    await send_telegram_message("🚀 *Smart Home Backend Online!*\nRunning smoothly on Raspberry Pi (Kubernetes).")
