import logging
from typing import Optional
from app.services.home_hardware import control_device
from app.models.device_model import ToggleResponse

logger = logging.getLogger(__name__)

async def execute_device_action(entity_id: str, action: str, timer_minutes: Optional[int] = None) -> str:
    """
    Controls a smart home device (e.g., light, switch, climate).
    
    Args:
        entity_id: The ID of the device to control, formatted as domain.name (e.g., switch.dvd_khshmly)
        action: The action to perform. Allowed values: 'turn_on', 'turn_off', 'toggle'
        timer_minutes: Optional number of minutes to run the device before automatically turning it off. 
                       Only applicable when turning a device on (action='turn_on' or action='toggle' if it turns on).
                       Maximum allowed timer is 60 minutes.
    """
    logger.info(f"AI requested action '{action}' on device '{entity_id}' with timer: {timer_minutes} mins")
    
    # 1. Enforce validation of action
    if action not in ("turn_on", "turn_off", "toggle"):
        return f"Failed: Invalid action '{action}'. Allowed values: 'turn_on', 'turn_off', 'toggle'."
        
    # 2. Check if the device exists and supports hardware timers
    from app.services.mongo_service import devices_collection
    device = await devices_collection.find_one({"entity_id": entity_id})
    supports_timer = device.get("supports_timer", False) if device else False
    
    # 3. Enforce timer validation and safety capping
    is_boiler = "boiler" in entity_id or "dvd" in entity_id
    if timer_minutes is not None:
        if not supports_timer:
            return f"Failed: Device '{entity_id}' does not support hardware timers. Only Switcher devices support timers."
        if timer_minutes <= 0:
            return "Failed: Timer duration must be greater than 0 minutes."
    # 4. Record action in the suppression window to prevent duplicate WebSocket notification
    from app.services.ha_listener import record_pending_action
    record_pending_action(entity_id)
            
    # 5. Perform action via Home Assistant (using control_device which forwards timer_minutes to Switcher native service)
    response: ToggleResponse = await control_device(entity_id, action, timer_minutes)
    
    if response.success:
        from app.services.mongo_service import update_device_state
        
        # Update MongoDB device state immediately
        await update_device_state(entity_id, response.new_state)
        
        # Handle passive timer metadata in MongoDB
        if action == "turn_off" or response.new_state == "off":
            await devices_collection.update_one(
                {"entity_id": entity_id},
                {"$set": {"timer_active": False, "timer_end": None}}
            )
            return f"Success: {response.message} (Any active hardware timer has been cleared)"
            
        elif action in ("turn_on", "toggle") and response.new_state != "off":
            if timer_minutes is not None:
                from datetime import datetime, timedelta, timezone
                timer_end = datetime.now(timezone.utc) + timedelta(minutes=timer_minutes)
                await devices_collection.update_one(
                    {"entity_id": entity_id},
                    {
                        "$set": {
                            "timer_active": True,
                            "timer_end": timer_end.isoformat()
                        }
                    }
                )
                suffix = " (Timer capped at 60 mins due to safety guardrail)" if is_boiler and timer_minutes == 60 else ""
                return f"Success: {response.message} (Native hardware timer set for {timer_minutes} minutes){suffix}"
            else:
                # Override: Action without timer clears active timer
                await devices_collection.update_one(
                    {"entity_id": entity_id},
                    {"$set": {"timer_active": False, "timer_end": None}}
                )
                return f"Success: {response.message}"
                
        return f"Success: {response.message}"
    else:
        return f"Failed: {response.message}"

# Define the list of tool functions that can be passed to the Gemini agent
agent_tools = [
    execute_device_action
]
