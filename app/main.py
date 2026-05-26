import os
import sys
import asyncio
import logging
from dotenv import load_dotenv

# Set up basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# Load environment variables first
load_dotenv()

from app.services.home_hardware import get_all_devices
from app.services.mongo_service import sync_devices_to_db
from app.controllers.bot_controller import start_polling

async def main():
    logger.info("Starting Smart Home AI Agent...")
    
    # 1. Fetch current devices from Home Assistant
    logger.info("Fetching devices from Home Assistant...")
    devices = await get_all_devices()
    
    # 2. Sync devices to MongoDB
    if devices:
        logger.info(f"Syncing {len(devices)} devices to MongoDB...")
        await sync_devices_to_db(devices)
    else:
        logger.warning("No devices fetched from Home Assistant. The context will be empty.")
        
    # 3. Start Telegram Bot Polling
    await start_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Smart Home AI Agent stopped.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
