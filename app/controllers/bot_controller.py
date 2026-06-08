import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from app.controllers.agent_core import process_user_message

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN is not set. Bot will not start.")

bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """
    Handles the /start command.
    """
    welcome_text = (
        "🤖 Welcome to your Smart Home AI Agent!\n"
        "I can help you control your home. Just tell me what you want to do."
    )
    await message.answer(welcome_text)

@dp.message()
async def handle_user_message(message: types.Message):
    """
    Catches all other text messages and routes them to the Gemini AI Agent.
    """
    if not message.text:
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    logger.info(f"Received message from {user_id} ({username}): {message.text}")
    
    # Send a typing action to Telegram so the user knows we are processing
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Immediately notify the user that the request was received
    await message.answer("הבקשה בטיפול... ⏳")
    
    # Route to Agent
    ai_response = await process_user_message(user_id=user_id, text=message.text, username=username)

    
    # Reply to the user
    await message.answer(ai_response)


async def send_startup_notification(devices):
    """
    Sends a startup message to the Telegram chat.
    Uses Gemini to format a friendly Hebrew message listing the online devices,
    with a fallback to a direct code-generated message.
    """
    from app.controllers.agent_core import client
    
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot or not chat_id:
        logger.warning("Bot or TELEGRAM_CHAT_ID not configured. Cannot send startup notification.")
        return
        
    try:
        chat_id_val = int(chat_id)
    except ValueError:
        chat_id_val = chat_id
        
    device_list_str = "\n".join([
        f"- {d.friendly_name or d.entity_id} ({'פעיל' if d.state == 'on' else 'כבוי' if d.state == 'off' else d.state})"
        for d in devices
    ])
    
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    prompt = (
        "Generate a friendly, welcoming startup notification in Hebrew for a smart home system. "
        "Announce that the system is now up and running (online). "
        "List the following connected devices that can be controlled and their current status:\n"
        f"{device_list_str}\n\n"
        "Keep it friendly, clear, and formatted nicely with emojis. "
        "Respond ONLY with the final Hebrew text, no quotes, no extra remarks."
    )
    
    notification_text = None
    if client:
        try:
            logger.info("Generating startup message using Gemini...")
            response = await client.aio.models.generate_content(
                model=gemini_model,
                contents=prompt
            )
            notification_text = response.text.strip()
        except Exception as e:
            logger.error(f"Failed to generate startup message using Gemini: {e}")
            
    if not notification_text:
        # Fallback Hebrew message
        device_lines = []
        for d in devices:
            status = "פעיל" if d.state == "on" else "כבוי" if d.state == "off" else d.state
            device_lines.append(f"• {d.friendly_name or d.entity_id}: {status}")
        
        devices_formatted = "\n".join(device_lines)
        notification_text = (
            "🤖 *מערכת הבית החכם עלתה בהצלחה!*\n\n"
            "המערכת מחוברת ומוכנה לקבלת פקודות. 🚀\n\n"
            "🔌 *המכשירים הזמינים לשליטה:*\n"
            f"{devices_formatted}"
        )
        
    try:
        logger.info(f"Sending startup notification to Telegram chat {chat_id}...")
        try:
            await bot.send_message(chat_id=chat_id_val, text=notification_text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Failed to send startup message with Markdown parsing: {e}. Retrying as HTML or plain text...")
            try:
                await bot.send_message(chat_id=chat_id_val, text=notification_text, parse_mode="HTML")
            except Exception as e_html:
                logger.warning(f"Failed to send startup message with HTML parsing: {e_html}. Retrying as plain text...")
                await bot.send_message(chat_id=chat_id_val, text=notification_text)
        logger.info("Startup notification sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send startup notification via Telegram: {e}")

async def start_polling():
    """
    Starts the Aiogram polling loop.
    """
    if bot:
        logger.info("Starting Telegram bot polling...")
        await dp.start_polling(bot)
    else:
        logger.error("Cannot start polling because bot is not initialized.")
