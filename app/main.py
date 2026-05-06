from fastapi import FastAPI
from pydantic import BaseModel
from typing import List

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