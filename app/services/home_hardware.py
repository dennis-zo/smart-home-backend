import os
import httpx
from typing import List
import logging
from app.models.device_model import HAEntity, ToggleResponse

logger = logging.getLogger(__name__)

# Fallback values for testing or configuration via .env
HA_URL = os.getenv("HA_URL", "http://localhost:8123/api")
HA_TOKEN = os.getenv("HA_TOKEN", "")

def get_headers() -> dict:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }

async def get_all_devices() -> List[HAEntity]:
    """
    Fetches all lights, switches, and climates from Home Assistant.
    """
    url = f"{HA_URL}/states"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=get_headers())
            response.raise_for_status()
            
            raw_entities = response.json()
            return [
                HAEntity.from_ha(entity) 
                for entity in raw_entities 
                if entity["entity_id"].startswith(("light.", "switch.", "climate."))
            ]
    except Exception as e:
        logger.error(f"Failed to fetch devices from Home Assistant: {e}")
        return []

async def toggle_device(entity_id: str) -> ToggleResponse:
    """
    Toggles a device state in Home Assistant.
    """
    domain = entity_id.split(".")[0]
    url = f"{HA_URL}/services/{domain}/toggle"
    payload = {"entity_id": entity_id}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=get_headers(), json=payload)
            response.raise_for_status()
            
            result_data = response.json()
            new_state = result_data[0]["state"] if result_data else "unknown"
            
            return ToggleResponse(
                success=True, 
                entity_id=entity_id, 
                new_state=new_state,
                message=f"Successfully toggled to {new_state}"
            )
    except Exception as e:
        logger.error(f"Failed to toggle device {entity_id}: {e}")
        return ToggleResponse(
            success=False, 
            entity_id=entity_id, 
            new_state="unknown",
            message=str(e)
        )
