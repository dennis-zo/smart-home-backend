import os
import httpx
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List
load_dotenv() # טוען את המשתנים מקובץ .env

app = FastAPI()

# נתונים להתחברות (ב-Kubernetes נגדיר אותם כ-ConfigMap או Secret)
HA_URL = os.getenv("HA_URL", "http://192.168.2.240:8123/api")
HA_TOKEN = os.getenv("HA_TOKEN")

headers = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

app = FastAPI(title="Smart Home Controller")

# "Interface" למכשיר
class Device(BaseModel):
    id: int
    name: str
    status: str = "off"

# Database זמני בזיכרון (במקום SQL כרגע)
db: List[Device] = [
    Device(id=1, name="Living Room Light"),
    Device(id=2, name="Kitchen AC")
]

@app.get("/")
def read_root():
    return {"status": "Home Controller Online"}

@app.get("/devices", response_model=List[Device])
async def get_devices():
    return db

@app.post("/devices/{device_id}/toggle")
async def toggle_device(device_id: int):
    for device in db:
        if device.id == device_id:
            device.status = "on" if device.status == "off" else "off"
            return device
    return {"error": "Device not found"}

@app.get("/ha/status")
async def get_ha_status():
    """בודק אם ה-API של HA זמין"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{HA_URL}/", headers=headers)
            return response.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/ha/entities")
async def get_all_entities():
    """מושך את כל המכשירים והחיישנים מהבית"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{HA_URL}/states", headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="HA Error")
        
        # נחזיר רק רשימה של שמות המכשירים והמצב שלהם (שימוש ב-List Comprehension!)
        all_states = response.json()
        return [
            {
                "entity_id": entity["entity_id"],
                "state": entity["state"],
                "friendly_name": entity.get("attributes", {}).get("friendly_name")
            }
            for entity in all_states
        ]