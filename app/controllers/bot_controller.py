import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from app.controllers.agent_core import process_user_message

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN is not set. Bot will not start.")

bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
dp = Dispatcher()

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Returns the main persistent reply keyboard containing quick-action buttons.
    """
    keyboard_buttons = [
        [
            KeyboardButton(text="תחילת יום עבודה 🟢"),
            KeyboardButton(text="סיום יום עבודה 🔴")
        ],
        [
            KeyboardButton(text="כמה זמן אני עובד היום? ⏱️"),
            KeyboardButton(text="מחק דיווח 🗑️")
        ],
        [
            KeyboardButton(text="הפעל 💡"),
            KeyboardButton(text="תסגור 🔌")
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard_buttons,
        resize_keyboard=True,
        persistent=True
    )

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """
    Handles the /start command.
    """
    welcome_text = (
        "🤖 Welcome to your Smart Home AI Agent!\n"
        "I can help you control your home. Just tell me what you want to do."
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message()
async def handle_user_message(message: types.Message):
    """
    Catches all other text messages and routes them to the Gemini AI Agent.
    """
    if not message.text:
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
       # Intercept deletion commands
    text_stripped = message.text.strip().lower()
    is_delete = False
    if text_stripped in ("מחק", "מחיקה", "מחק דיווח", "למחוק", "למחוק דיווח", "מחק דיווח 🗑️"):
        is_delete = True
    elif text_stripped.startswith(("מחק ", "מחיקה ", "למחוק ")):
        is_delete = True
        
    if is_delete:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        from app.services.mongo_service import clockwork_collection
        from datetime import datetime
        
        # Fetch the last 5 reports for this username
        cursor = clockwork_collection.find({
            "name": username
        }).sort([("date", -1), ("start_time", -1)]).limit(5)
        records = await cursor.to_list(length=5)
        
        if not records:
            await message.answer("לא נמצאו דיווחים במערכת! 📭", reply_markup=get_main_keyboard())
            return
            
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        for r in records:
            r_id = str(r["_id"])
            date_str = r.get("date", "")
            try:
                date_formatted = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m")
            except Exception:
                date_formatted = date_str
                
            event_type = r.get("type_of_event", "work")
            hours = r.get("hours")
            
            if event_type == "work":
                start_time = r.get("start_time")
                end_time = r.get("end_time")
                if start_time and end_time:
                    btn_text = f"📅 {date_formatted} | עבודה {start_time}-{end_time} ({hours} ש')"
                elif start_time:
                    btn_text = f"📅 {date_formatted} | עבודה פעיל מ-{start_time}"
                else:
                    btn_text = f"📅 {date_formatted} | עבודה"
            elif event_type == "sick":
                btn_text = f"📅 {date_formatted} | יום מחלה ({hours} ש')"
            else:
                btn_text = f"📅 {date_formatted} | יום חופש ({hours} ש')"
                
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"delete_req:{r_id}")])
            
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("בחר דיווח למחיקה: 👇", reply_markup=keyboard)
        return
 
    # Intercept "הפעל" message
    match message.text.strip():
        case "הפעל" | "הפעל 💡":
            await bot.send_chat_action(chat_id=message.chat.id, action="typing")
            from app.services.home_hardware import get_all_devices
            devices = await get_all_devices()
            devices_to_turn_on = [d for d in devices if d.state == "off"]
            
            if not devices_to_turn_on:
                await message.answer("כל המכשירים כבר מופעלים! 💡", reply_markup=get_main_keyboard())
                return
                
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            buttons = []
            for d in devices_to_turn_on:
                name = d.friendly_name or d.entity_id
                buttons.append([InlineKeyboardButton(text=f"הפעל את {name}", callback_data=f"turn_on:{d.entity_id}")])
                
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer("בחר מכשיר להפעלה: 👇", reply_markup=keyboard)
        case "תסגור" | "תסגור 🔌":
            await bot.send_chat_action(chat_id=message.chat.id, action="typing")
            from app.services.home_hardware import get_all_devices
            devices = await get_all_devices()
            devices_to_turn_off = [d for d in devices if d.state == "on"]
            
            if not devices_to_turn_off:
                await message.answer("כל המכשירים כבר כבויים! 💡", reply_markup=get_main_keyboard())
                return
                
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            buttons = []
            for d in devices_to_turn_off:
                name = d.friendly_name or d.entity_id
                buttons.append([InlineKeyboardButton(text=f"תסגור את {name}", callback_data=f"turn_off:{d.entity_id}")])
                
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer("בחר מכשיר לסגירה: 👇", reply_markup=keyboard)


        case _: # זה ה-default,
            # Send a typing action to Telegram so the user knows we are processing
            await bot.send_chat_action(chat_id=message.chat.id, action="typing")
            
            # Immediately notify the user that the request was received
            await message.answer("הבקשה בטיפול... ⏳")
    
            # Route to Agent
            ai_response = await process_user_message(user_id=user_id, text=message.text, username=username)

            # Reply to the user
            await message.answer(ai_response, reply_markup=get_main_keyboard())

@dp.callback_query()
async def handle_callback_query(callback_query: types.CallbackQuery):
    """
    Handles inline keyboard button clicks.
    """
    data = callback_query.data
    if not data:
        return
        
    if data.startswith("turn_on:"):
        entity_id = data.split(":", 1)[1]
        
        # Answer the callback query so the loading indicator on Telegram disappears
        await callback_query.answer()
        
        # Execute the turn on action using our core tool definition
        from app.agents.tool_definitions import execute_device_action
        
        # Find device friendly name first for a nicer response
        from app.services.mongo_service import devices_collection
        device = await devices_collection.find_one({"entity_id": entity_id})
        friendly_name = device.get("friendly_name") if device else entity_id
        if not friendly_name:
            friendly_name = entity_id
            
        await callback_query.message.answer(f"מפעיל את {friendly_name}... ⏳")
        
        result = await execute_device_action(entity_id=entity_id, action="turn_on")
        
        if "Success" in result:
            await callback_query.message.answer(f"✅ {friendly_name} הופעל בהצלחה!")
        else:
            await callback_query.message.answer(f"❌ נכשל להפעיל את {friendly_name}: {result}")

    elif data.startswith("turn_off:"):
        entity_id = data.split(":", 1)[1]
        
        # Answer the callback query so the loading indicator on Telegram disappears
        await callback_query.answer()
        
        # Execute the turn off action using our core tool definition
        from app.agents.tool_definitions import execute_device_action
        
        # Find device friendly name first for a nicer response
        from app.services.mongo_service import devices_collection
        device = await devices_collection.find_one({"entity_id": entity_id})
        friendly_name = device.get("friendly_name") if device else entity_id
        if not friendly_name:
            friendly_name = entity_id
            
        await callback_query.message.answer(f"סוגר את {friendly_name}... ⏳")
        
        result = await execute_device_action(entity_id=entity_id, action="turn_off")
        
        if "Success" in result:
            await callback_query.message.answer(f"✅ {friendly_name} נסגר בהצלחה!")
        else:
            await callback_query.message.answer(f"❌ נכשל לסגור את {friendly_name}: {result}")

    elif data.startswith("delete_req:"):
        record_id = data.split(":", 1)[1]
        await callback_query.answer()
        
        from app.services.mongo_service import clockwork_collection
        from bson import ObjectId
        
        try:
            record = await clockwork_collection.find_one({"_id": ObjectId(record_id)})
        except Exception:
            record = None
            
        if not record:
            await callback_query.message.answer("❌ הדיווח לא נמצא או שכבר נמחק.")
            return
            
        date_str = record.get("date", "")
        event_type = record.get("type_of_event", "work")
        hours = record.get("hours")
        description = record.get("description", "")
        
        hebrew_type = "עבודה" if event_type == "work" else "מחלה" if event_type == "sick" else "חופש"
        
        details = f"📅 תאריך: {date_str}\n"
        details += f"🏷️ סוג: {hebrew_type}\n"
        
        if event_type == "work":
            start_time = record.get("start_time")
            end_time = record.get("end_time")
            if start_time:
                details += f"⏰ שעת כניסה: {start_time}\n"
            if end_time:
                details += f"⏰ שעת יציאה: {end_time}\n"
                
        if hours is not None:
            details += f"⏳ שעות: {hours}\n"
            
        if description:
            details += f"📝 הערה: {description}\n"
            
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        confirm_buttons = [
            [
                InlineKeyboardButton(text="✅ כן, מחק", callback_data=f"delete_confirm:{record_id}"),
                InlineKeyboardButton(text="❌ ביטול", callback_data="delete_cancel")
            ]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=confirm_buttons)
        
        await callback_query.message.answer(
            f"❓ *האם אתה בטוח שברצונך למחוק את הדיווח הבא?*\n\n{details}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    elif data.startswith("delete_confirm:"):
        record_id = data.split(":", 1)[1]
        await callback_query.answer()
        
        from app.services.mongo_service import clockwork_collection
        from bson import ObjectId
        
        try:
            result = await clockwork_collection.delete_one({"_id": ObjectId(record_id)})
            if result.deleted_count > 0:
                await callback_query.message.answer("✅ הדיווח נמחק בהצלחה!")
            else:
                await callback_query.message.answer("❌ הדיווח לא נמצא או שכבר נמחק.")
        except Exception as e:
            await callback_query.message.answer(f"❌ שגיאה במחיקת הדיווח: {e}")

    elif data == "delete_cancel":
        await callback_query.answer("המחיקה בוטלה.")
        await callback_query.message.answer("המחיקה בוטלה. ↩️")


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
    
    from app.controllers.agent_core import generate_content_with_failover
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
            response = await generate_content_with_failover(contents=prompt)
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
            await bot.send_message(chat_id=chat_id_val, text=notification_text, parse_mode="Markdown", reply_markup=get_main_keyboard())
        except Exception as e:
            logger.warning(f"Failed to send startup message with Markdown parsing: {e}. Retrying as HTML or plain text...")
            try:
                await bot.send_message(chat_id=chat_id_val, text=notification_text, parse_mode="HTML", reply_markup=get_main_keyboard())
            except Exception as e_html:
                logger.warning(f"Failed to send startup message with HTML parsing: {e_html}. Retrying as plain text...")
                await bot.send_message(chat_id=chat_id_val, text=notification_text, reply_markup=get_main_keyboard())
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
