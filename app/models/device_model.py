from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class HAEntity(BaseModel):
    """
    Standard device model for Home Assistant entities.
    """
    entity_id: str
    state: str
    friendly_name: Optional[str] = None
    
    @classmethod
    def from_ha(cls, data: Dict[str, Any]) -> "HAEntity":
        """
        Parses raw Home Assistant state JSON into our domain model.
        """
        attributes = data.get("attributes", {})
        return cls(
            entity_id=data.get("entity_id", ""),
            state=data.get("state", "unknown"),
            friendly_name=attributes.get("friendly_name")
        )

class DeviceState(BaseModel):
    """
    Model for MongoDB storage and Context Injection.
    """
    entity_id: str
    state: str
    friendly_name: Optional[str] = None
    
    @classmethod
    def from_ha_entity(cls, entity: HAEntity) -> "DeviceState":
        return cls(
            entity_id=entity.entity_id,
            state=entity.state,
            friendly_name=entity.friendly_name
        )

class ToggleResponse(BaseModel):
    success: bool
    entity_id: str
    new_state: str
    message: Optional[str] = None
