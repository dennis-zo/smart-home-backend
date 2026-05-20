import os
import httpx
from fastapi import APIRouter

telegram_router = APIRouter(prefix="/telegram", tags=["telegram"])

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_message(text: str):
    """פונקציית עזר אסינכרונית לשליחת הודעה לטלגרם"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram environment variables are missing!")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            return response.status_code == 200
        except Exception as e:
            print(f"❌ Failed to send Telegram message: {e}")
            return False

# Endpoint שטלגרם יכול לקרוא לו (Webhook) כדי לשלוט בבית מהצ'אט
@telegram_router.post("/webhook")
async def telegram_webhook(update: dict):
    """מקבל הודעות מהבוט של טלגרם ומבצע פקודות"""
    message = update.get("message", {})
    text = message.get("text", "")
    
    if text == "/status":
        await send_telegram_message("🏠 All systems operational.")
    elif text == "/lights_off":
        # כאן בעתיד תוכל לקרוא ללוגיקה שמכבה את כל האורות בבת אחת
        await send_telegram_message("🛑 Request received: Turning off all lights (TBD).")
        
    return {"status": "ok"} 

@telegram_router.post("/sendmessage")
async def telegram_sendmessage(message: str):
    """שולח הודעה לטלגרם"""
    await send_telegram_message(message)
    return {"status": "ok"} 
