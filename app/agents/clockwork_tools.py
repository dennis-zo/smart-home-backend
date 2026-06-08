import json
import logging
import calendar
import re
from datetime import datetime, timedelta, date
from typing import Optional
from zoneinfo import ZoneInfo
from bson import ObjectId
from app.services.mongo_service import clockwork_collection

logger = logging.getLogger(__name__)
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

def get_local_now() -> datetime:
    """Returns the current datetime in Israel Timezone."""
    return datetime.now(ISRAEL_TZ)

def parse_date_string(date_str: Optional[str]) -> str:
    """
    Parses a date string in various common formats and returns 'YYYY-MM-DD'.
    If date_str is None or empty, returns today's date in Israel.
    """
    if not date_str:
        return get_local_now().strftime("%Y-%m-%d")
        
    date_str = date_str.strip()
    # Handle common delimiters: slash, dot, hyphen
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%y", "%d.%m.%y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    # Try parsing D/M/YYYY or DD/M/YYYY etc. via regex
    m = re.match(r"^(\d{1,2})[/\.-](\d{1,2})[/\.-](\d{2,4})$", date_str)
    if m:
        d, month_val, y = m.groups()
        if len(y) == 2:
            y = "20" + y # assume 20xx
        try:
            dt = date(int(y), int(month_val), int(d))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
            
    raise ValueError(f"Unrecognized date format: {date_str}. Please use DD/MM/YYYY or YYYY-MM-DD.")

def format_time_to_hhmm(time_str: str) -> str:
    """
    Ensures a time string is formatted as HH:MM.
    Supports 'H:MM', 'HH:MM', 'H', 'HH'.
    """
    time_str = time_str.strip()
    if time_str.isdigit():
        val = int(time_str)
        if 0 <= val <= 23:
            return f"{val:02d}:00"
            
    m = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if m:
        h, minutes = m.groups()
        if 0 <= int(h) <= 23 and 0 <= int(minutes) <= 59:
            return f"{int(h):02d}:{int(minutes):02d}"
            
    raise ValueError(f"Unrecognized time format: {time_str}. Please use HH:MM.")

def format_hours_to_hhmm(hours: float) -> str:
    """Converts a float number of hours to 'H:MM' string format."""
    total_minutes = int(round(hours * 60))
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h}:{m:02d}"

async def start_work(
    username: str,
    start_time: Optional[str] = None,
    date: Optional[str] = None,
    description: Optional[str] = None
) -> str:
    """
    Logs the start of a work session. 
    If start_time or date are not specified, current local values are used.
    
    Args:
        username: The name of the user starting work.
        start_time: Optional. The start time (e.g. '09:00', '14:30'). Defaults to current local time.
        date: Optional. The work date (e.g. '08/06/2026', '2026-06-08'). Defaults to current local date.
        description: Optional. A short remark/description. Defaults to 'יום עבודה'.
    """
    try:
        now = get_local_now()
        target_date = parse_date_string(date) if date else now.strftime("%Y-%m-%d")
        target_time = start_time.strip() if start_time else now.strftime("%H:%M")
        target_time = format_time_to_hhmm(target_time)

        # Check if there is an active session (end_time is None) for this user on this day
        active_session = await clockwork_collection.find_one({
            "name": username,
            "date": target_date,
            "type_of_event": "work",
            "end_time": None
        })
        if active_session:
            return json.dumps({
                "status": "warning",
                "message": f"כבר יש יום עבודה פעיל לתאריך {target_date} שהתחיל ב-{active_session['start_time']}.",
                "data": {
                    "id": str(active_session["_id"]),
                    "date": active_session["date"],
                    "start_time": active_session["start_time"],
                    "description": active_session.get("description", "")
                }
            }, ensure_ascii=False)

        doc = {
            "name": username,
            "date": target_date,
            "type_of_event": "work",
            "start_time": target_time,
            "end_time": None,
            "time_event": None,
            "hours": None,
            "description": description or "יום עבודה"
        }
        result = await clockwork_collection.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        
        return json.dumps({
            "status": "success",
            "message": f"נרשמה תחילת יום עבודה ב-{target_time} עבור {target_date}.",
            "data": doc
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in start_work: {e}")
        return json.dumps({"status": "error", "message": f"שגיאה ברישום תחילת יום עבודה: {str(e)}"}, ensure_ascii=False)

async def end_work(
    username: str,
    end_time: Optional[str] = None,
    date: Optional[str] = None,
    description: Optional[str] = None
) -> str:
    """
    Logs the end of a work session.
    If end_time or date are not specified, current local values are used.
    Finds the latest work session where end_time is null.
    
    Args:
        username: The name of the user ending work.
        end_time: Optional. The end time (e.g. '18:00', '17:30'). Defaults to current local time.
        date: Optional. The date of end (e.g. '08/06/2026'). Defaults to current local date.
        description: Optional. A short remark/description to append/overwrite.
    """
    try:
        now = get_local_now()
        target_date = parse_date_string(date) if date else now.strftime("%Y-%m-%d")
        target_time = end_time.strip() if end_time else now.strftime("%H:%M")
        target_time = format_time_to_hhmm(target_time)

        # To handle overnight shifts and standard usage, look for the most recent active session
        # overall, sorted by date and start_time descending
        cursor = clockwork_collection.find({
            "name": username,
            "type_of_event": "work",
            "end_time": None
        }).sort([("date", -1), ("start_time", -1)]).limit(1)
        active_sessions = await cursor.to_list(length=1)

        if not active_sessions:
            return json.dumps({
                "status": "error",
                "message": "לא נמצא יום עבודה פעיל שניתן לסיים. אנא התחל יום עבודה קודם לכן."
            }, ensure_ascii=False)

        session = active_sessions[0]
        session_id = session["_id"]
        start_date_str = session["date"]
        start_time_str = session["start_time"]

        # Calculate time difference
        start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")

        if end_dt < start_dt:
            return json.dumps({
                "status": "error",
                "message": f"שעת סיום ({target_date} {target_time}) היא לפני שעת התחלה ({start_date_str} {start_time_str})."
            }, ensure_ascii=False)

        duration = end_dt - start_dt
        duration_seconds = duration.total_seconds()
        hours = round(duration_seconds / 3600.0, 2)
        
        hours_part = int(duration_seconds // 3600)
        minutes_part = int((duration_seconds % 3600) // 60)
        time_event_str = f"{hours_part}:{minutes_part:02d}"

        update_fields = {
            "end_time": target_time,
            "time_event": time_event_str,
            "hours": hours
        }
        if description:
            update_fields["description"] = description

        await clockwork_collection.update_one(
            {"_id": session_id},
            {"$set": update_fields}
        )

        session.update(update_fields)
        session["_id"] = str(session["_id"])

        return json.dumps({
            "status": "success",
            "message": f"סיום יום עבודה עודכן ל-{target_time}. סה\"כ שעות: {time_event_str}.",
            "data": session
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in end_work: {e}")
        return json.dumps({"status": "error", "message": f"שגיאה ברישום סיום יום עבודה: {str(e)}"}, ensure_ascii=False)

async def record_day_off(
    username: str,
    start_date: str,
    end_date: Optional[str] = None,
    hours: float = 8.5,
    description: Optional[str] = None
) -> str:
    """
    Logs a day off (vacation) or a range of vacation days.
    
    Args:
        username: The name of the user.
        start_date: The start date of vacation (e.g. '01/06/2026').
        end_date: Optional. The end date of vacation (inclusive). If omitted, logs only a single day.
        hours: The vacation hours to log per day. Defaults to 8.5.
        description: Optional description. Defaults to 'יום חופש'.
    """
    try:
        start_date_str = parse_date_string(start_date)
        end_date_str = parse_date_string(end_date) if end_date else start_date_str

        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()

        if end_dt < start_dt:
            return json.dumps({"status": "error", "message": "תאריך סיום לא יכול להיות לפני תאריך התחלה."}, ensure_ascii=False)

        current_dt = start_dt
        inserted_docs = []
        
        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            doc = {
                "name": username,
                "date": date_str,
                "type_of_event": "day_off",
                "start_time": None,
                "end_time": None,
                "time_event": format_hours_to_hhmm(hours),
                "hours": hours,
                "description": description or "יום חופש"
            }
            result = await clockwork_collection.insert_one(doc)
            doc["_id"] = str(result.inserted_id)
            inserted_docs.append(doc)
            current_dt += timedelta(days=1)

        days_count = len(inserted_docs)
        date_range_str = f"עבור {start_date_str}" if days_count == 1 else f"מ-{start_date_str} עד {end_date_str}"
        
        return json.dumps({
            "status": "success",
            "message": f"נרשמו {days_count} ימי חופש {date_range_str} ({hours} שעות ליום).",
            "data": inserted_docs
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in record_day_off: {e}")
        return json.dumps({"status": "error", "message": f"שגיאה ברישום יום חופש: {str(e)}"}, ensure_ascii=False)

async def record_sick_leave(
    username: str,
    start_date: str,
    end_date: Optional[str] = None,
    hours: float = 8.5,
    description: Optional[str] = None
) -> str:
    """
    Logs a sick leave or a range of sick leave days.
    
    Args:
        username: The name of the user.
        start_date: The start date of sick leave (e.g. '01/06/2026').
        end_date: Optional. The end date of sick leave (inclusive). If omitted, logs only a single day.
        hours: The sick leave hours to log per day. Defaults to 8.5.
        description: Optional description. Defaults to 'יום מחלה'.
    """
    try:
        start_date_str = parse_date_string(start_date)
        end_date_str = parse_date_string(end_date) if end_date else start_date_str

        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()

        if end_dt < start_dt:
            return json.dumps({"status": "error", "message": "תאריך סיום לא יכול להיות לפני תאריך התחלה."}, ensure_ascii=False)

        current_dt = start_dt
        inserted_docs = []
        
        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            doc = {
                "name": username,
                "date": date_str,
                "type_of_event": "sick_leave",
                "start_time": None,
                "end_time": None,
                "time_event": format_hours_to_hhmm(hours),
                "hours": hours,
                "description": description or "יום מחלה"
            }
            result = await clockwork_collection.insert_one(doc)
            doc["_id"] = str(result.inserted_id)
            inserted_docs.append(doc)
            current_dt += timedelta(days=1)

        days_count = len(inserted_docs)
        date_range_str = f"עבור {start_date_str}" if days_count == 1 else f"מ-{start_date_str} עד {end_date_str}"
        
        return json.dumps({
            "status": "success",
            "message": f"נרשמו {days_count} ימי מחלה {date_range_str} ({hours} שעות ליום).",
            "data": inserted_docs
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in record_sick_leave: {e}")
        return json.dumps({"status": "error", "message": f"שגיאה ברישום יום מחלה: {str(e)}"}, ensure_ascii=False)

async def get_hours_summary(
    username: str,
    period: str,
    date: Optional[str] = None
) -> str:
    """
    Calculates the sum of hours and returns details for the specified period: 'day', 'week', or 'month'.
    Weekly summary covers Sunday to Thursday of the week containing the date.
    
    Args:
        username: The name of the user.
        period: The duration type. Allowed values: 'day', 'week', 'month'.
        date: Optional. The target date for the query. Defaults to current local date.
    """
    try:
        now = get_local_now()
        target_date_str = parse_date_string(date) if date else now.strftime("%Y-%m-%d")
        target_date_obj = datetime.strptime(target_date_str, "%Y-%m-%d").date()

        if period == "day":
            start_date_str = target_date_str
            end_date_str = target_date_str
            label = f"יום {target_date_str}"
        elif period == "week":
            # Israel week is Sunday to Thursday
            wd = target_date_obj.weekday()
            # In python, Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
            if wd == 6:
                sunday_obj = target_date_obj
            else:
                sunday_obj = target_date_obj - timedelta(days=(wd + 1))
            thursday_obj = sunday_obj + timedelta(days=4)
            start_date_str = sunday_obj.strftime("%Y-%m-%d")
            end_date_str = thursday_obj.strftime("%Y-%m-%d")
            label = f"השבוע מ-{start_date_str} עד {end_date_str}"
        elif period == "month":
            year = target_date_obj.year
            month = target_date_obj.month
            last_day = calendar.monthrange(year, month)[1]
            start_date_str = f"{year}-{month:02d}-01"
            end_date_str = f"{year}-{month:02d}-{last_day}"
            label = f"חודש {year}-{month:02d}"
        else:
            return json.dumps({
                "status": "error", 
                "message": f"תקופה לא חוקית: '{period}'. ערכים מותרים: 'day', 'week', 'month'."
            }, ensure_ascii=False)

        cursor = clockwork_collection.find({
            "name": username,
            "date": {"$gte": start_date_str, "$lte": end_date_str}
        }).sort([("date", 1), ("start_time", 1)])
        events = await cursor.to_list(length=1000)

        total_hours = 0.0
        details = []
        
        for ev in events:
            h = ev.get("hours") or 0.0
            total_hours += h
            details.append({
                "id": str(ev["_id"]),
                "date": ev["date"],
                "type": ev["type_of_event"],
                "start_time": ev.get("start_time"),
                "end_time": ev.get("end_time"),
                "time_event": ev.get("time_event"),
                "hours": h,
                "description": ev.get("description", "")
            })

        total_hours_str = format_hours_to_hhmm(total_hours)

        return json.dumps({
            "status": "success",
            "period": period,
            "label": label,
            "total_hours": total_hours,
            "total_hours_formatted": total_hours_str,
            "events_count": len(details),
            "data": details
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in get_hours_summary: {e}")
        return json.dumps({"status": "error", "message": f"שגיאה בחישוב סיכום שעות: {str(e)}"}, ensure_ascii=False)

async def get_current_work_duration(username: str) -> str:
    """
    Calculates elapsed hours since starting the current active work session.
    
    Args:
        username: The name of the user.
    """
    try:
        cursor = clockwork_collection.find({
            "name": username,
            "type_of_event": "work",
            "end_time": None
        }).sort([("date", -1), ("start_time", -1)]).limit(1)
        active_sessions = await cursor.to_list(length=1)

        if not active_sessions:
            return json.dumps({
                "status": "inactive",
                "message": "לא נמצא יום עבודה פעיל שרץ כרגע."
            }, ensure_ascii=False)

        session = active_sessions[0]
        start_date_str = session["date"]
        start_time_str = session["start_time"]

        start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
        now = get_local_now().replace(tzinfo=None)
        
        if now < start_dt:
            elapsed_seconds = 0.0
        else:
            elapsed_seconds = (now - start_dt).total_seconds()

        hours = round(elapsed_seconds / 3600.0, 2)
        hours_part = int(elapsed_seconds // 3600)
        minutes_part = int((elapsed_seconds % 3600) // 60)
        time_event_str = f"{hours_part}:{minutes_part:02d}"

        return json.dumps({
            "status": "active",
            "message": f"נמצא יום עבודה פעיל שהתחיל ב-{start_time_str} ({start_date_str}).",
            "data": {
                "date": start_date_str,
                "start_time": start_time_str,
                "elapsed_time": time_event_str,
                "hours": hours,
                "description": session.get("description", "")
            }
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in get_current_work_duration: {e}")
        return json.dumps({"status": "error", "message": f"שגיאה בחישוב משך עבודה נוכחי: {str(e)}"}, ensure_ascii=False)

async def correct_work_hours(
    username: str,
    date: str,
    event_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    hours: Optional[float] = None,
    type_of_event: Optional[str] = None,
    description: Optional[str] = None
) -> str:
    """
    Corrects a record's fields for a given date. If multiple events exist, requires event_id.
    
    Args:
        username: The name of the user.
        date: The date of the record to correct (e.g. '08/06/2026').
        event_id: Optional. The ID of the specific MongoDB record to correct, if multiple exist for the date.
        start_time: Optional. The new start time (e.g. '08:30').
        end_time: Optional. The new end time (e.g. '17:00').
        hours: Optional. The new hours (used for day off/sick leave, or manual override).
        type_of_event: Optional. The new event type ('work', 'day_off', 'sick_leave').
        description: Optional. The new description.
    """
    try:
        target_date_str = parse_date_string(date)

        if event_id:
            try:
                db_filter = {"_id": ObjectId(event_id), "name": username}
            except Exception:
                return json.dumps({"status": "error", "message": f"מזהה רשומה לא חוקי: {event_id}."}, ensure_ascii=False)
        else:
            db_filter = {"name": username, "date": target_date_str}

        cursor = clockwork_collection.find(db_filter)
        events = await cursor.to_list(length=10)

        if not events:
            return json.dumps({
                "status": "error",
                "message": f"לא נמצאו רשומות לתאריך {target_date_str} עבור המשתמש {username}."
            }, ensure_ascii=False)

        if len(events) > 1 and not event_id:
            details = []
            for ev in events:
                details.append({
                    "id": str(ev["_id"]),
                    "type": ev["type_of_event"],
                    "start": ev.get("start_time"),
                    "end": ev.get("end_time"),
                    "hours": ev.get("hours"),
                    "description": ev.get("description", "")
                })
            return json.dumps({
                "status": "multiple_found",
                "message": f"נמצאו מספר רשומות לתאריך {target_date_str}. אנא ספק מזהה (id) של הרשומה שברצונך לעדכן.",
                "data": details
            }, ensure_ascii=False)

        event = events[0]
        event_id_obj = event["_id"]

        update_fields = {}
        
        new_type = type_of_event or event.get("type_of_event")
        new_start = start_time or event.get("start_time")
        new_end = end_time or event.get("end_time")
        new_hours = hours
        
        if type_of_event:
            update_fields["type_of_event"] = new_type

        if new_type == "work":
            if start_time:
                update_fields["start_time"] = format_time_to_hhmm(start_time)
            if end_time:
                update_fields["end_time"] = format_time_to_hhmm(end_time)

            curr_start = update_fields.get("start_time", event.get("start_time"))
            curr_end = update_fields.get("end_time", event.get("end_time"))

            if curr_start and curr_end:
                start_dt = datetime.strptime(f"{target_date_str} {curr_start}", "%Y-%m-%d %H:%M")
                end_dt = datetime.strptime(f"{target_date_str} {curr_end}", "%Y-%m-%d %H:%M")
                if end_dt < start_dt:
                    return json.dumps({
                        "status": "error",
                        "message": f"שעת סיום ({curr_end}) לא יכולה להיות לפני שעת התחלה ({curr_start})."
                    }, ensure_ascii=False)
                
                duration_seconds = (end_dt - start_dt).total_seconds()
                calc_hours = round(duration_seconds / 3600.0, 2)
                hours_part = int(duration_seconds // 3600)
                minutes_part = int((duration_seconds % 3600) // 60)
                time_event_str = f"{hours_part}:{minutes_part:02d}"

                update_fields["hours"] = calc_hours
                update_fields["time_event"] = time_event_str
        else:
            # Day off or Sick leave has no start/end times
            update_fields["start_time"] = None
            update_fields["end_time"] = None
            if new_hours is not None:
                update_fields["hours"] = new_hours
                update_fields["time_event"] = format_hours_to_hhmm(new_hours)
            elif event.get("hours") is None:
                update_fields["hours"] = 8.5
                update_fields["time_event"] = "8:30"

        if description:
            update_fields["description"] = description

        await clockwork_collection.update_one(
            {"_id": event_id_obj},
            {"$set": update_fields}
        )

        event.update(update_fields)
        event["_id"] = str(event["_id"])

        return json.dumps({
            "status": "success",
            "message": "הרשומה עודכנה בהצלחה.",
            "data": event
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in correct_work_hours: {e}")
        return json.dumps({"status": "error", "message": f"שגיאה בעדכון הרשומה: {str(e)}"}, ensure_ascii=False)

async def delete_month_records(
    username: str,
    year: int,
    month: int
) -> str:
    """
    Deletes all hour logs for the specified user and completed month.
    Does not allow deleting the current or future months.
    
    Args:
        username: The name of the user.
        year: The year of the month to delete (e.g. 2026).
        month: The month number to delete (1-12).
    """
    try:
        now = get_local_now()
        curr_year = now.year
        curr_month = now.month

        # Current or future month guardrail
        if (year > curr_year) or (year == curr_year and month >= curr_month):
            return json.dumps({
                "status": "error",
                "message": f"לא ניתן למחוק את החודש הנוכחי או חודשים עתידיים ({year}-{month:02d}). החודש חייב להסתיים תחילה."
            }, ensure_ascii=False)

        month_prefix = f"^{year}-{month:02d}"
        result = await clockwork_collection.delete_many({
            "name": username,
            "date": {"$regex": month_prefix}
        })

        return json.dumps({
            "status": "success",
            "message": f"נמחקו בהצלחה {result.deleted_count} רשומות עבור חודש {year}-{month:02d}.",
            "data": {
                "deleted_count": result.deleted_count
            }
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in delete_month_records: {e}")
        return json.dumps({"status": "error", "message": f"שגיאה במחיקת רשומות חודשיות: {str(e)}"}, ensure_ascii=False)

# List of clockwork tool functions for the Gemini agent
clockwork_tools = [
    start_work,
    end_work,
    record_day_off,
    record_sick_leave,
    get_hours_summary,
    get_current_work_duration,
    correct_work_hours,
    delete_month_records
]
