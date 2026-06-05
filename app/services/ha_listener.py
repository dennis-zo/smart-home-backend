import os
import asyncio
import logging
import json
import time
import aiohttp
from app.services.mongo_service import update_device_state

logger = logging.getLogger(__name__)

HA_URL = os.getenv("HA_URL", "http://localhost:8123/api")
HA_TOKEN = os.getenv("HA_TOKEN", "")

# In-memory dictionary tracking recent bot-initiated actions to suppress duplicate notifications
# Maps entity_id -> float timestamp
_pending_bot_actions = {}

def record_pending_action(entity_id: str):
    """
    Records that the bot has initiated an action on a device.
    Used to suppress duplicate notifications from WebSocket events.
    """
    _pending_bot_actions[entity_id] = time.time()
    logger.info(f"Recorded pending bot action for {entity_id} at {time.time()}")

def is_action_pending(entity_id: str) -> bool:
    """
    Checks if there is a recent bot-initiated action for the device (within 5 seconds).
    """
    timestamp = _pending_bot_actions.get(entity_id)
    if timestamp:
        elapsed = time.time() - timestamp
        if elapsed < 5.0:
            logger.info(f"Action is pending for {entity_id} (elapsed: {elapsed:.2f}s). Notification will be suppressed.")
            return True
    return False

def get_websocket_url() -> str:
    """
    Constructs the Home Assistant WebSocket API URL based on HA_URL.
    """
    ws_url = HA_URL.replace("http://", "ws://").replace("https://", "wss://")
    if not ws_url.endswith("/websocket"):
        ws_url = ws_url.rstrip("/") + "/websocket"
    return ws_url

async def send_ai_notification(entity_id: str, new_state: str, friendly_name: str):
    """
    Calls Gemini to generate a friendly notification in Hebrew and sends it via Telegram.
    """
    from app.controllers.agent_core import client
    from app.controllers.bot_controller import bot
    
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot or not chat_id or not client:
        logger.warning("Bot, Chat ID, or Gemini Client not configured. Cannot send AI notification.")
        return
        
    prompt = (
        f"Generate a short, natural, and clear notification message in Hebrew for the user "
        f"indicating that the device '{friendly_name}' (ID: {entity_id}) has changed its state to '{new_state}'. "
        f"Keep it very brief, friendly, and suitable for a Telegram message. "
        f"Respond ONLY with the notification text, do not add quotes or any other words."
    )
    
    try:
        # Generate content using gemini-2.5-flash
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        notification_text = response.text.strip()
        
        # Send via Telegram
        await bot.send_message(chat_id=chat_id, text=notification_text)
        logger.info(f"Sent AI notification for {entity_id}: {notification_text}")
    except Exception as e:
        logger.error(f"Failed to generate or send AI notification for {entity_id}: {e}")

async def start_ha_listener():
    """
    Launches the persistent Home Assistant WebSocket event listener loop.
    Re-establishes connection automatically if disconnected.
    """
    ws_url = get_websocket_url()
    logger.info(f"Starting HA WebSocket Listener on {ws_url}...")

    if not HA_TOKEN:
        logger.error("HA_TOKEN is missing. Cannot start WebSocket listener.")
        return

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url) as ws:
                    logger.info("Connected to Home Assistant WebSocket API. Authenticating...")
                    
                    # Connection Loop
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            msg_type = data.get("type")

                            # 1. Handle Authentication Handshake
                            if msg_type == "auth_required":
                                auth_msg = {
                                    "type": "auth",
                                    "access_token": HA_TOKEN
                                }
                                await ws.send_json(auth_msg)
                                logger.info("Sent auth token to Home Assistant.")

                            elif msg_type == "auth_ok":
                                logger.info("Authentication successful! Subscribing to state changes...")
                                subscribe_msg = {
                                    "id": 1,
                                    "type": "subscribe_events",
                                    "event_type": "state_changed"
                                }
                                await ws.send_json(subscribe_msg)

                            elif msg_type == "auth_invalid":
                                logger.error(f"Failed to authenticate with HA: {data.get('message')}")
                                break  # Break loop to reconnect after a delay

                            # 2. Process Subscribed Events
                            elif msg_type == "event":
                                event_data = data.get("event", {})
                                if event_data.get("event_type") == "state_changed":
                                    event_details = event_data.get("data", {})
                                    entity_id = event_details.get("entity_id")
                                    new_state_obj = event_details.get("new_state")

                                    # Ignore entities without state changes or entities we do not track
                                    if not entity_id or not new_state_obj:
                                        continue

                                    if entity_id.startswith(("switch.", "light.", "climate.")):
                                        new_state = new_state_obj.get("state")
                                        
                                        # Query DB to check if the state actually changed
                                        from app.services.mongo_service import devices_collection
                                        current_device = await devices_collection.find_one({"entity_id": entity_id})
                                        old_state = current_device.get("state") if current_device else None
                                        
                                        if old_state != new_state:
                                            logger.info(f"Received HA event: {entity_id} changed state to {new_state} (was {old_state})")
                                            
                                            # Update DB
                                            await update_device_state(entity_id, new_state)
                                            
                                            # Check if this change was triggered by the bot itself
                                            if is_action_pending(entity_id):
                                                logger.info(f"Suppressed duplicate AI notification for {entity_id} (bot action pending)")
                                            else:
                                                # Send Telegram notification in the background
                                                friendly_name = current_device.get("friendly_name") if current_device else entity_id
                                                if not friendly_name:
                                                    friendly_name = entity_id
                                                asyncio.create_task(send_ai_notification(entity_id, new_state, friendly_name))

                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                            logger.warning("WebSocket connection closing or closed by server.")
                            break

        except aiohttp.ClientConnectorError as e:
            logger.error(f"Failed to connect to HA WebSocket (Server offline?): {e}")
        except Exception as e:
            logger.error(f"Error in HA WebSocket listener loop: {e}", exc_info=True)

        logger.info("Attempting to reconnect to Home Assistant WebSocket in 5 seconds...")
        await asyncio.sleep(5)
