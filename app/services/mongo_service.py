import os
import logging
from typing import List
from motor.motor_asyncio import AsyncIOMotorClient
from app.models.device_model import DeviceState

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "smarthome_db")

client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB_NAME]
devices_collection = db["devices"]

async def sync_devices_to_db(devices: List[DeviceState]):
    """
    Upserts the current list of devices into MongoDB.
    """
    if not devices:
        logger.warning("No devices to sync to MongoDB.")
        return

    try:
        for device in devices:
            await devices_collection.update_one(
                {"entity_id": device.entity_id},
                {"$set": device.model_dump()},
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
            context_lines.append(f"- {name} (ID: {entity_id}): {state}")
            
        return "\n".join(context_lines)
    except Exception as e:
        logger.error(f"Error fetching device context: {e}")
        return "Error fetching device context."
