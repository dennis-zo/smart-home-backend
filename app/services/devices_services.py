import os
import httpx
from fastapi import APIRouter, HTTPException
from typing import List
from app.models import HAEntity, ToggleResponse
from app.services.telegram_services import send_telegram_message

devices_router = APIRouter(prefix="/devices", tags=["devices"])

HA_URL = os.getenv("HA_URL")
HA_TOKEN = os.getenv("HA_TOKEN")

headers = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

@devices_router.get("", response_model=List[HAEntity])
async def get_all_devices():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{HA_URL}/states", headers=headers)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="HA API Error")
            
            raw_entities = response.json()
            return [
                HAEntity.from_ha(entity) 
                for entity in raw_entities 
                if entity["entity_id"].startswith(("light.", "switch.", "climate."))
            ]
        except httpx.RequestError as exc:
            raise HTTPException(status_code=500, detail=f"Connection to HA failed: {exc}")

@devices_router.post("/toggle/{entity_id}", response_model=ToggleResponse)
async def toggle_device(entity_id: str):
    domain = entity_id.split(".")[0]
    url = f"{HA_URL}/services/{domain}/toggle"
    payload = {"entity_id": entity_id}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Failed to toggle device {entity_id}")
        
        result_data = response.json()
        new_state = result_data[0]["state"] if result_data else "unknown"
        
        # בונוס: שליחת עדכון לטלגרם על שינוי מצב המכשיר בבית!
        await send_telegram_message(f"🔄 *Device Updated:*\n`{entity_id}` is now *{new_state.upper()}*")
        
        return ToggleResponse(success=True, entity_id=entity_id, new_state=new_state)
