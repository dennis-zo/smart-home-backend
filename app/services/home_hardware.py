import os
import httpx
import logging
from typing import List, Optional
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

async def control_device(entity_id: str, action: str, timer_minutes: Optional[int] = None) -> ToggleResponse:
    """
    Controls a device state in Home Assistant (turn_on, turn_off, toggle).
    Supports native Switcher timers if timer_minutes is provided.
    """
    domain = entity_id.split(".")[0]
    
    if action == "turn_on" and timer_minutes is not None:
        url = f"{HA_URL}/services/switcher_kis/turn_on_with_timer"
        payload = {
            "entity_id": entity_id,
            "timer_minutes": timer_minutes
        }
    else:
        if action not in ("turn_on", "turn_off", "toggle"):
            raise ValueError(f"Invalid action: {action}")
        url = f"{HA_URL}/services/{domain}/{action}"
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
                message=f"Successfully set {entity_id} to {new_state}"
            )
    except Exception as e:
        logger.error(f"Failed to control device {entity_id} ({action}): {e}")
        return ToggleResponse(
            success=False, 
            entity_id=entity_id, 
            new_state="unknown",
            message=str(e)
        )

async def toggle_device(entity_id: str) -> ToggleResponse:
    """
    Toggles a device state in Home Assistant.
    """
    return await control_device(entity_id, "toggle")
