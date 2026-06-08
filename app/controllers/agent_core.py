import os
import logging
from zoneinfo import ZoneInfo
from datetime import datetime
# pyrefly: ignore [missing-import]
from google import genai
# pyrefly: ignore [missing-import]
from google.genai import types
from app.agents.orchestrator import get_system_instruction
from app.agents.tool_definitions import agent_tools
from app.agents.clockwork_agent import get_clockwork_system_instruction
from app.agents.clockwork_tools import clockwork_tools
from app.services.mongo_service import get_device_context, sync_devices_to_db
from app.services.home_hardware import get_all_devices

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Initialize the Gemini client
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY is not set. The agent will not be able to call the API.")
    client = None

# Using an in-memory session history map per user (keyed by user_id)
_sessions = {}
_clockwork_sessions = {}

async def classify_message(text: str) -> str:
    """
    Classifies the user message into either 'clockwork' or 'smarthome'.
    """
    if not client:
        return "smarthome"
        
    prompt = (
        "You are a routing assistant for a smart home and work hour tracking system.\n"
        "Analyze the user request and classify it into one of two categories:\n"
        "1. 'clockwork': If the request is about work hours, logging time, clocking in (start work), "
        "clocking out (end work), vacation/day off (חופש), sick leave (מחלה), query/summary of hours, "
        "fixing/correcting hours, or deleting hour logs.\n"
        "2. 'smarthome': If the request is about smart home control (lights, boiler/דוד, switches, state check, turning things on/off), "
        "or if it is a general chat, greeting, or unclear.\n\n"
        "Respond ONLY with either 'clockwork' or 'smarthome' (no markdown, no quotes, no extra characters).\n\n"
        f"User request: \"{text}\""
    )
    
    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
            )
        )
        result = response.text.strip().lower()
        if "clockwork" in result:
            return "clockwork"
        return "smarthome"
    except Exception as e:
        logger.error(f"Classification failed: {e}. Defaulting to smarthome.")
        return "smarthome"

async def process_user_message(user_id: int, text: str, username: str) -> str:
    """
    Processes a message from the user via the Gemini AI Agent, routing to either
    the SmartHome Agent or the ClockWork Agent based on request classification.
    """
    if not client:
        return "I'm sorry, my AI backend is not configured correctly (missing API key)."

    # 1. Classify the user request
    category = await classify_message(text)
    logger.info(f"Classified request from {username} as category: {category}")

    if category == "clockwork":
        # Dynamic context for ClockWork (profile, local date, day of week, current time)
        israel_now = datetime.now(ZoneInfo("Asia/Jerusalem"))
        current_date_str = israel_now.strftime("%Y-%m-%d")
        current_time_str = israel_now.strftime("%H:%M")
        day_name_hebrew = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"][israel_now.weekday()]
        
        dynamic_context = (
            f"[User Profile]:\n"
            f"- Username: {username}\n"
            f"- Current Time: {current_time_str}\n"
            f"- Current Date: {current_date_str} (יום {day_name_hebrew})\n\n"
        )
        
        if user_id not in _clockwork_sessions:
            system_inst = get_clockwork_system_instruction()
            config = types.GenerateContentConfig(
                system_instruction=system_inst,
                tools=clockwork_tools,
                temperature=0.0
            )
            _clockwork_sessions[user_id] = client.aio.chats.create(
                model=GEMINI_MODEL,
                config=config
            )
            
        chat = _clockwork_sessions[user_id]
        prompt_with_context = f"{dynamic_context}[User Request]: {text}"
        
        try:
            response = await chat.send_message(prompt_with_context)
            return response.text
        except Exception as e:
            logger.error(f"Error communicating with Gemini (ClockWork): {e}")
            return "מצטער, נתקלתי בשגיאה בעת עיבוד הבקשה שלך לשעות עבודה."

    else:
        # 1. Fetch fresh states from Home Assistant and sync to MongoDB
        logger.info("Fetching fresh device states from Home Assistant...")
        try:
            devices = await get_all_devices()
            if devices:
                await sync_devices_to_db(devices)
        except Exception as e:
            logger.error(f"Failed to sync fresh devices to DB before message processing: {e}")

        # 2. Fetch current device context from MongoDB
        device_context = await get_device_context()
        
        # 3. Build the system prompt (static instructions only)
        dynamic_system_instruction = get_system_instruction()

        # 4. Initialize or retrieve the chat session
        if user_id not in _sessions:
            config = types.GenerateContentConfig(
                system_instruction=dynamic_system_instruction,
                tools=agent_tools,
                temperature=0.0
            )
            _sessions[user_id] = client.aio.chats.create(
                model=GEMINI_MODEL,
                config=config
            )

        chat = _sessions[user_id]
        prompt_with_context = f"[Latest Device Context]:\n{device_context}\n\n[User Request]: {text}"

        try:
            response = await chat.send_message(prompt_with_context)
            return response.text
        except Exception as e:
            logger.error(f"Error communicating with Gemini (SmartHome): {e}")
            return "I'm sorry, I encountered an error while processing your request."

