import os
import httpx
from fastapi import FastAPI, HTTPException
from typing import List
from app.models import HAEntity, ToggleResponse

# טעינת משתני סביבה (אם יש קובץ .env)
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Smart Home Core API")

HA_URL = os.getenv("HA_URL", "http://homeassistant.local:8123/api")
HA_TOKEN = os.getenv("HA_TOKEN")

if not HA_TOKEN:
    print("⚠️ Warning: HA_TOKEN is not set in environment variables!")

headers = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

@app.get("/devices", response_model=List[HAEntity])
async def get_all_devices():
    """מושך את כל המכשירים מהבית ומסנן רק את האורות והמזגנים"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{HA_URL}/states", headers=headers)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="HA API Error")
            
            raw_entities = response.json()
            
            # שימוש ב-List Comprehension חכם עם פילטר
            return [
                HAEntity.from_ha(entity) 
                for entity in raw_entities 
                if entity["entity_id"].startswith(("light.", "switch.", "climate."))
            ]
        except httpx.RequestError as exc:
            raise HTTPException(status_code=500, detail=f"Connection to HA failed: {exc}")

@app.post("/devices/toggle/{entity_id}", response_model=ToggleResponse)
async def toggle_device(entity_id: str):
    """שולח פקודת Toggle (הדלקה/כיבוי) למכשיר ספציפי בבית"""
    # קביעת ה-domain (למשל: light או switch) מתוך ה-entity_id
    domain = entity_id.split(".")[0]
    url = f"{HA_URL}/services/{domain}/toggle"
    
    payload = {"entity_id": entity_id}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Failed to toggle device {entity_id}")
        
        # מושכים את המצב החדש מתוך התשובה של HA
        result_data = response.json()
        new_state = result_data[0]["state"] if result_data else "unknown"
        
        return ToggleResponse(success=True, entity_id=entity_id, new_state=new_state)