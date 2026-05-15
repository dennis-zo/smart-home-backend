from pydantic import BaseModel
from typing import Optional, Dict, Any

class HAEntity(BaseModel):
    entity_id: str
    state: str
    friendly_name: Optional[str] = None
    
    # פונקציה שהופכת את ה-JSON של Home Assistant למודל שלנו
    @classmethod
    def from_ha(cls, data: Dict[str, Any]):
        attributes = data.get("attributes", {})
        return cls(
            entity_id=data.get("entity_id"),
            state=data.get("state"),
            friendly_name=attributes.get("friendly_name")
        )

class ToggleResponse(BaseModel):
    success: bool
    entity_id: str
    new_state: str