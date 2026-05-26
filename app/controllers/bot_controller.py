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
    logger.info(f"Received message from {user_id}: {message.text}")
    
    # Send a typing action to Telegram so the user knows we are processing
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Route to Agent
    ai_response = await process_user_message(user_id=user_id, text=message.text)
    
    # Reply to the user
    await message.answer(ai_response)

async def start_polling():
    """
    Starts the Aiogram polling loop.
    """
    if bot:
        logger.info("Starting Telegram bot polling...")
        await dp.start_polling(bot)
    else:
        logger.error("Cannot start polling because bot is not initialized.")
