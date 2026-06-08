import os
import logging
import httpx
import json
import asyncio
from typing import List
# pyrefly: ignore [missing-import]
from motor.motor_asyncio import AsyncIOMotorClient
from app.models.device_model import DeviceState

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "smarthome_db")

client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB_NAME]
devices_collection = db["devices"]
clockwork_collection = db["clockwork"]


async def get_switcher_entities() -> List[str]:
    """
    Queries Home Assistant to identify all entities manufactured by Switcher.
    """
    from app.services.home_hardware import HA_URL, get_headers
    url = f"{HA_URL}/template"
    template = """
    {% set ns = namespace(entities=[]) %}
    {% for s in states.switch %}
      {% if device_attr(s.entity_id, 'manufacturer') == 'Switcher' %}
        {% set ns.entities = ns.entities + [s.entity_id] %}
      {% endif %}
    {% endfor %}
    {{ ns.entities | tojson }}
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=get_headers(), json={"template": template})
            response.raise_for_status()
            return json.loads(response.text.strip())
    except Exception as e:
        logger.error(f"Failed to fetch switcher entities from HA template: {e}")
        return []

async def sync_devices_to_db(devices: List[DeviceState]):
    """
    Upserts the current list of devices into MongoDB.
    """
    if not devices:
        logger.warning("No devices to sync to MongoDB.")
        return

    try:
        switcher_entities = await get_switcher_entities()
        for device in devices:
            supports_timer = device.entity_id in switcher_entities
            
            # If the device is off in Home Assistant, clear its active timer fields in DB.
            if device.state == "off":
                await devices_collection.update_one(
                    {"entity_id": device.entity_id},
                    {
                        "$set": {
                            "state": device.state,
                            "friendly_name": device.friendly_name,
                            "supports_timer": supports_timer,
                            "timer_active": False,
                            "timer_end": None
                        }
                    },
                    upsert=True
                )
            else:
                await devices_collection.update_one(
                    {"entity_id": device.entity_id},
                    {
                        "$set": {
                            "state": device.state,
                            "friendly_name": device.friendly_name,
                            "supports_timer": supports_timer
                        },
                        "$setOnInsert": {
                            "timer_active": False,
                            "timer_end": None
                        }
                    },
                    upsert=True
                )
        logger.info(f"Successfully synced {len(devices)} devices to MongoDB.")
    except Exception as e:
        logger.error(f"MongoDB Sync Error: {e}")

async def get_device_context() -> str:
    """
    Retrieves all synced devices from MongoDB and formats them as a context string.
    """
    try:
        cursor = devices_collection.find({}, {"_id": 0})
        devices = await cursor.to_list(length=1000)
        
        if not devices:
            return "No devices found in the database context."

        context_lines = []
        for d in devices:
            name = d.get("friendly_name", d.get("entity_id"))
            state = d.get("state", "unknown")
            entity_id = d.get("entity_id")
            supports_timer = d.get("supports_timer", False)
            timer_active = d.get("timer_active", False)
            timer_end_str = d.get("timer_end")
            
            timer_info = ""
            if supports_timer:
                if timer_active and timer_end_str:
                    try:
                        from datetime import datetime, timezone
                        timer_end = datetime.fromisoformat(timer_end_str)
                        now = datetime.now(timezone.utc) if timer_end.tzinfo else datetime.now()
                        if now < timer_end:
                            remaining = timer_end - now
                            remaining_mins = max(0, int(remaining.total_seconds() / 60))
                            timer_info = f" (Timer Active: {remaining_mins} min remaining)"
                        else:
                            timer_info = " (Timer Inactive)"
                            # Passive clear expired timer metadata in DB
                            asyncio.create_task(devices_collection.update_one(
                                {"entity_id": entity_id},
                                {"$set": {"timer_active": False, "timer_end": None}}
                            ))
                    except Exception:
                        timer_info = " (Timer Active)"
                else:
                    timer_info = " (Timer Inactive)"
            else:
                timer_info = " (Timer Not Supported)"
                
            context_lines.append(f"- {name} (ID: {entity_id}): {state}{timer_info}")
            
        return "\n".join(context_lines)
    except Exception as e:
        logger.error(f"Error fetching device context: {e}")
        return "Error fetching device context."

async def update_device_state(entity_id: str, state: str):
    """
    Updates the state of a single device in MongoDB.
    Clears active timer fields passively if the state is turned off.
    """
    try:
        if state == "off":
            await devices_collection.update_one(
                {"entity_id": entity_id},
                {
                    "$set": {
                        "state": state,
                        "timer_active": False,
                        "timer_end": None
                    }
                }
            )
        else:
            await devices_collection.update_one(
                {"entity_id": entity_id},
                {"$set": {"state": state}}
            )
        logger.info(f"Updated MongoDB device {entity_id} to state: {state}")
    except Exception as e:
        logger.error(f"Failed to update MongoDB state for {entity_id}: {e}")

