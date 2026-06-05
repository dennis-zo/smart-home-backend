import os
import logging
# pyrefly: ignore [missing-import]
from google import genai
# pyrefly: ignore [missing-import]
from google.genai import types
from app.agents.orchestrator import get_system_instruction
from app.agents.tool_definitions import agent_tools
from app.services.mongo_service import get_device_context, sync_devices_to_db
from app.services.home_hardware import get_all_devices

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize the Gemini client
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY is not set. The agent will not be able to call the API.")
    client = None

# Using an in-memory session history map per user (keyed by user_id)
# This keeps it simple without storing the entire chat history in MongoDB right now.
_sessions = {}

async def process_user_message(user_id: int, text: str) -> str:
    """
    Processes a message from the user via the Gemini AI Agent.
    """
    if not client:
        return "I'm sorry, my AI backend is not configured correctly (missing API key)."

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


    # 3. Initialize or retrieve the chat session
    if user_id not in _sessions:
        config = types.GenerateContentConfig(
            system_instruction=dynamic_system_instruction,
            tools=agent_tools,
            temperature=0.0
        )
        _sessions[user_id] = client.aio.chats.create(
            model="gemini-2.5-flash",
            config=config
        )
    else:
        # If session exists, we should ideally update the system_instruction for new context.
        # But `genai` chat sessions don't easily allow updating system instructions mid-chat.
        # For this implementation, we will pass the updated context as a hidden user message,
        # or we just rely on the tool calls (if we had a get_status tool). 
        # To strictly follow the guardrail, we'll prepend the latest context to the user's prompt.
        pass

    chat = _sessions[user_id]
    
    # We append the context to the user's message so the agent always has the freshest state.
    prompt_with_context = f"[Latest Device Context]:\n{device_context}\n\n[User Request]: {text}"

    try:
        # 4. Send the message to Gemini
        response = await chat.send_message(prompt_with_context)
        return response.text
    except Exception as e:
        logger.error(f"Error communicating with Gemini: {e}")
        return "I'm sorry, I encountered an error while processing your request."
