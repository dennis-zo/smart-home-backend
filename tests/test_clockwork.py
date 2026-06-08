import os
import unittest
import asyncio
import json
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from bson import ObjectId
from dotenv import load_dotenv
load_dotenv()


# Patch the collection in mongo_service and clockwork_tools
import app.services.mongo_service as mongo_service
import app.agents.clockwork_tools as cw_tools

class TestClockWork(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        # Re-initialize client inside the test's active event loop to prevent Closed Loop errors
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_service.client = AsyncIOMotorClient(mongo_service.MONGO_URI)
        mongo_service.db = mongo_service.client[mongo_service.MONGO_DB_NAME]
        
        self.test_collection = mongo_service.db["clockwork_test"]
        mongo_service.clockwork_collection = self.test_collection
        cw_tools.clockwork_collection = self.test_collection
        
        # Clean up any leftover data
        await self.test_collection.delete_many({})

    async def asyncTearDown(self):
        # Clean up database after each test
        await self.test_collection.delete_many({})


    def test_date_parsing(self):
        # Test parse_date_string helper
        self.assertEqual(cw_tools.parse_date_string("05/06/2026"), "2026-06-05")
        self.assertEqual(cw_tools.parse_date_string("5/6/2026"), "2026-06-05")
        self.assertEqual(cw_tools.parse_date_string("2026-06-05"), "2026-06-05")
        self.assertEqual(cw_tools.parse_date_string("05.06.26"), "2026-06-05")
        with self.assertRaises(ValueError):
            cw_tools.parse_date_string("not-a-date")

    def test_time_formatting(self):
        # Test format_time_to_hhmm helper
        self.assertEqual(cw_tools.format_time_to_hhmm("9"), "09:00")
        self.assertEqual(cw_tools.format_time_to_hhmm("17"), "17:00")
        self.assertEqual(cw_tools.format_time_to_hhmm("09:30"), "09:30")
        self.assertEqual(cw_tools.format_time_to_hhmm("9:05"), "09:05")
        with self.assertRaises(ValueError):
            cw_tools.format_time_to_hhmm("25:00")

    async def test_start_work(self):
        # Test start_work
        res_str = await cw_tools.start_work(username="test_user", start_time="09:00", date="2026-06-08", description="משמרת בוקר")
        res = json.loads(res_str)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["data"]["start_time"], "09:00")
        self.assertEqual(res["data"]["date"], "2026-06-08")
        self.assertEqual(res["data"]["description"], "משמרת בוקר")

        # Test duplicate start warning
        duplicate_res_str = await cw_tools.start_work(username="test_user", start_time="10:00", date="2026-06-08")
        duplicate_res = json.loads(duplicate_res_str)
        self.assertEqual(duplicate_res["status"], "warning")
        self.assertIn("כבר יש יום עבודה פעיל", duplicate_res["message"])

    async def test_end_work(self):
        # First start work
        await cw_tools.start_work(username="test_user", start_time="09:30", date="2026-06-08")

        # Test end_work
        end_res_str = await cw_tools.end_work(username="test_user", end_time="17:45", date="2026-06-08", description="סיום יום")
        end_res = json.loads(end_res_str)
        self.assertEqual(end_res["status"], "success")
        self.assertEqual(end_res["data"]["end_time"], "17:45")
        # 09:30 to 17:45 is 8 hours 15 minutes = 8.25 hours
        self.assertEqual(end_res["data"]["hours"], 8.25)
        self.assertEqual(end_res["data"]["time_event"], "8:15")
        self.assertEqual(end_res["data"]["description"], "סיום יום")

        # Test no active session error
        error_res_str = await cw_tools.end_work(username="test_user", end_time="18:00", date="2026-06-08")
        error_res = json.loads(error_res_str)
        self.assertEqual(error_res["status"], "error")

    async def test_overnight_shift(self):
        # Start work on June 7 at 22:00
        await cw_tools.start_work(username="test_user", start_time="22:00", date="2026-06-07")
        # End work on June 8 at 06:30
        end_res_str = await cw_tools.end_work(username="test_user", end_time="06:30", date="2026-06-08")
        end_res = json.loads(end_res_str)
        self.assertEqual(end_res["status"], "success")
        # 22:00 to 06:30 is 8.5 hours
        self.assertEqual(end_res["data"]["hours"], 8.5)
        self.assertEqual(end_res["data"]["time_event"], "8:30")

    async def test_record_day_off_and_sick_leave(self):
        # Record single day off
        res_str = await cw_tools.record_day_off(username="test_user", start_date="2026-06-01", description="חופש מתוכנן")
        res = json.loads(res_str)
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["data"]), 1)
        self.assertEqual(res["data"][0]["type_of_event"], "day_off")
        self.assertEqual(res["data"][0]["hours"], 8.5)

        # Record range of sick leaves
        res_str = await cw_tools.record_sick_leave(username="test_user", start_date="2026-06-02", end_date="2026-06-04", hours=4.0)
        res = json.loads(res_str)
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["data"]), 3)
        self.assertEqual(res["data"][0]["date"], "2026-06-02")
        self.assertEqual(res["data"][1]["date"], "2026-06-03")
        self.assertEqual(res["data"][2]["date"], "2026-06-04")
        self.assertEqual(res["data"][0]["hours"], 4.0)
        self.assertEqual(res["data"][0]["time_event"], "4:00")

    async def test_get_hours_summary(self):
        # Insert various events:
        # Sunday 2026-06-07: work 8 hours
        # Monday 2026-06-08: work 9 hours
        # Tuesday 2026-06-09: day off (8.5 hours)
        # Friday 2026-06-12: work 3 hours (should be excluded from weekly total since Israel week is Sun-Thu)
        
        await cw_tools.start_work(username="test_user", start_time="08:00", date="2026-06-07")
        await cw_tools.end_work(username="test_user", end_time="16:00", date="2026-06-07")
        
        await cw_tools.start_work(username="test_user", start_time="09:00", date="2026-06-08")
        await cw_tools.end_work(username="test_user", end_time="18:00", date="2026-06-08")

        await cw_tools.record_day_off(username="test_user", start_date="2026-06-09", hours=8.5)
        
        # Friday (out of Sun-Thu range)
        await cw_tools.start_work(username="test_user", start_time="09:00", date="2026-06-12")
        await cw_tools.end_work(username="test_user", end_time="12:00", date="2026-06-12")

        # Test daily summary
        day_res_str = await cw_tools.get_hours_summary(username="test_user", period="day", date="2026-06-08")
        day_res = json.loads(day_res_str)
        self.assertEqual(day_res["total_hours"], 9.0)

        # Test weekly summary (should find Sun 7 to Thu 11)
        # Should sum Sunday (8h) + Monday (9h) + Tuesday (8.5h) = 25.5 hours. Friday (3h) must be skipped.
        week_res_str = await cw_tools.get_hours_summary(username="test_user", period="week", date="2026-06-08")
        week_res = json.loads(week_res_str)
        self.assertEqual(week_res["total_hours"], 25.5)
        self.assertEqual(week_res["total_hours_formatted"], "25:30")
        self.assertEqual(week_res["events_count"], 3)

        # Test monthly summary (should sum all, including Friday, since they are in June)
        month_res_str = await cw_tools.get_hours_summary(username="test_user", period="month", date="2026-06-08")
        month_res = json.loads(month_res_str)
        self.assertEqual(month_res["total_hours"], 28.5) # 25.5 + 3.0

    async def test_get_current_work_duration(self):
        # No active work session
        dur_res_str = await cw_tools.get_current_work_duration(username="test_user")
        dur_res = json.loads(dur_res_str)
        self.assertEqual(dur_res["status"], "inactive")

        # Start an active session
        # Use a timezone-aware local time of 2 hours ago to mock elapsed time
        now = cw_tools.get_local_now()
        start_time_obj = now - timedelta(hours=2)
        start_time_str = start_time_obj.strftime("%H:%M")
        start_date_str = start_time_obj.strftime("%Y-%m-%d")

        await cw_tools.start_work(username="test_user", start_time=start_time_str, date=start_date_str)
        
        dur_res_str = await cw_tools.get_current_work_duration(username="test_user")
        dur_res = json.loads(dur_res_str)
        self.assertEqual(dur_res["status"], "active")
        # should show around 2.0 hours (allow small float variations due to execution time)
        self.assertAlmostEqual(dur_res["data"]["hours"], 2.00, delta=0.05)

    async def test_correct_work_hours(self):
        # Insert a record
        res_str = await cw_tools.start_work(username="test_user", start_time="09:00", date="2026-06-08")
        event = json.loads(res_str)["data"]
        event_id = event["_id"]

        # Correct start time and end time
        correct_res_str = await cw_tools.correct_work_hours(
            username="test_user",
            date="2026-06-08",
            event_id=event_id,
            start_time="10:00",
            end_time="15:30",
            description="תיקון מיוחד"
        )
        correct_res = json.loads(correct_res_str)
        self.assertEqual(correct_res["status"], "success")
        self.assertEqual(correct_res["data"]["hours"], 5.5)
        self.assertEqual(correct_res["data"]["time_event"], "5:30")
        self.assertEqual(correct_res["data"]["description"], "תיקון מיוחד")

        # Test multiple records detection
        # Insert another event for the same day
        await cw_tools.record_day_off(username="test_user", start_date="2026-06-08", hours=3.0)
        
        multiple_res_str = await cw_tools.correct_work_hours(
            username="test_user",
            date="2026-06-08",
            start_time="11:00"
        )
        multiple_res = json.loads(multiple_res_str)
        self.assertEqual(multiple_res["status"], "multiple_found")
        self.assertEqual(len(multiple_res["data"]), 2)

    async def test_delete_month_records_guardrail(self):
        # We need to test the guardrail for deleting current or future month
        now = cw_tools.get_local_now()
        curr_year = now.year
        curr_month = now.month

        # Try to delete current month (should fail)
        fail_res_str = await cw_tools.delete_month_records(username="test_user", year=curr_year, month=curr_month)
        fail_res = json.loads(fail_res_str)
        self.assertEqual(fail_res["status"], "error")
        self.assertIn("לא ניתן למחוק את החודש הנוכחי", fail_res["message"])

        # Try to delete past month (should succeed)
        # Find a month in the past
        past_date = now - timedelta(days=40)
        past_year = past_date.year
        past_month = past_date.month

        # Insert some dummy records in the past month
        past_date_str = past_date.strftime("%Y-%m-%d")
        await cw_tools.start_work(username="test_user", start_time="09:00", date=past_date_str)

        success_res_str = await cw_tools.delete_month_records(username="test_user", year=past_year, month=past_month)
        success_res = json.loads(success_res_str)
        self.assertEqual(success_res["status"], "success")
        self.assertEqual(success_res["data"]["deleted_count"], 1)

if __name__ == "__main__":
    unittest.main()
