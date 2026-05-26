import logging
from app.services.home_hardware import toggle_device
from app.models.device_model import ToggleResponse

logger = logging.getLogger(__name__)

async def execute_toggle_device(entity_id: str) -> str:
    """
    Toggles a smart home device (e.g., light, switch, climate).
    
    Args:
        entity_id: The ID of the device to toggle, formatted as domain.name (e.g., light.living_room)
    """
    logger.info(f"AI requested to toggle device: {entity_id}")
    response: ToggleResponse = await toggle_device(entity_id)
    
    if response.success:
        return f"Success: {response.message}"
    else:
        return f"Failed: {response.message}"

# Define the list of tool functions that can be passed to the Gemini agent
agent_tools = [
    execute_toggle_device
]
