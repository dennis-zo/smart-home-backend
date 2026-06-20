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

# Using an in-memory session history map per user (keyed by user_id)
_sessions = {}
_clockwork_sessions = {}

# Parse models configuration
GEMINI_MODELS_ENV = os.getenv("GEMINI_MODELS", "gemini-3.5-flash")
GEMINI_MODELS = [m.strip() for m in GEMINI_MODELS_ENV.split(",") if m.strip()]
if not GEMINI_MODELS:
    GEMINI_MODELS = ["gemini-3.5-flash", "gemini-2.5-flash"]

_current_model_index = 0

def get_current_model() -> str:
    global _current_model_index
    return GEMINI_MODELS[_current_model_index]

def switch_to_next_model():
    global _current_model_index
    old_model = get_current_model()
    _current_model_index = (_current_model_index + 1) % len(GEMINI_MODELS)
    new_model = get_current_model()
    logger.info(f"Switching active model from {old_model} to {new_model}")
    _sessions.clear()
    _clockwork_sessions.clear()

# Initialize the Gemini client
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY is not set. The agent will not be able to call the API.")
    client = None

async def generate_content_with_failover(contents, config=None):
    """
    Wrapper for client.aio.models.generate_content that supports automatic model failover.
    """
    if not client:
        raise Exception("Gemini client is not initialized.")
        
    attempts = 0
    max_attempts = len(GEMINI_MODELS)
    last_error = None
    
    while attempts < max_attempts:
        model = get_current_model()
        try:
            logger.info(f"Attempting generate_content with model: {model}")
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
            return response
        except Exception as e:
            logger.error(f"Error generating content with model {model}: {e}")
            last_error = e
            switch_to_next_model()
            attempts += 1
            
    raise Exception(f"All models failed. Last error: {last_error}")

async def send_chat_message_with_failover(user_id: int, chat_type: str, text: str, system_instruction_func, tools, temperature=0.0):
    """
    Wrapper for sending messages in a chat session with automatic model failover.
    """
    if not client:
        raise Exception("Gemini client is not initialized.")
        
    attempts = 0
    max_attempts = len(GEMINI_MODELS)
    last_error = None
    
    while attempts < max_attempts:
        model = get_current_model()
        
        if chat_type == "clockwork":
            sessions_dict = _clockwork_sessions
        else:
            sessions_dict = _sessions
            
        if user_id not in sessions_dict:
            logger.info(f"Creating new chat session for user {user_id} using model {model}")
            system_inst = system_instruction_func()
            config = types.GenerateContentConfig(
                system_instruction=system_inst,
                tools=tools,
                temperature=temperature
            )
            sessions_dict[user_id] = client.aio.chats.create(
                model=model,
                config=config
            )
            
        chat = sessions_dict[user_id]
        
        try:
            logger.info(f"Sending message in chat for {chat_type} using model {model}")
            response = await chat.send_message(text)
            return response
        except Exception as e:
            logger.error(f"Error sending chat message with model {model}: {e}")
            last_error = e
            switch_to_next_model()
            attempts += 1
            
    raise Exception(f"All models failed. Last error: {last_error}")

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
        response = await generate_content_with_failover(
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
        logger.error(f"Classification failed completely: {e}")
        raise e

async def process_user_message(user_id: int, text: str, username: str) -> str:
    """
    Processes a message from the user via the Gemini AI Agent, routing to either
    the SmartHome Agent or the ClockWork Agent based on request classification.
    """
    if not client:
        return "I'm sorry, my AI backend is not configured correctly (missing API key)."

    # 1. Classify the user request
    try:
        category = await classify_message(text)
    except Exception as e:
        logger.error(f"Classification failed completely: {e}")
        return f"בעיה בחיבור למודל AI:\n{e}"
        
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
        
        prompt_with_context = f"{dynamic_context}[User Request]: {text}"
        
        try:
            response = await send_chat_message_with_failover(
                user_id=user_id,
                chat_type="clockwork",
                text=prompt_with_context,
                system_instruction_func=get_clockwork_system_instruction,
                tools=clockwork_tools,
                temperature=0.0
            )
            return response.text
        except Exception as e:
            logger.error(f"Error communicating with Gemini (ClockWork): {e}")
            return f"בעיה בחיבור למודל AI:\n{e}"

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

        prompt_with_context = f"[Latest Device Context]:\n{device_context}\n\n[User Request]: {text}"

        try:
            response = await send_chat_message_with_failover(
                user_id=user_id,
                chat_type="smarthome",
                text=prompt_with_context,
                system_instruction_func=get_system_instruction,
                tools=agent_tools,
                temperature=0.0
            )
            return response.text
        except Exception as e:
            logger.error(f"Error communicating with Gemini (SmartHome): {e}")
            return f"בעיה בחיבור למודל AI:\n{e}"


