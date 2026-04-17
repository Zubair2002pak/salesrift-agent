import os
import pickle
import re
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta, date
import pytz
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDAR_ID = 'primary'
def clean_email(email):
    email = email.strip().lower()
    # Convert spoken email format to real email
    # e.g. "z-u-b-a-i-r dot a-z-h-a-r-k-h-a-n at gmail dot com"
    # Step 1: replace " at " and " dot " with @ and .
    email = re.sub(r'\s+at\s+', '@', email)
    email = re.sub(r'\s+dot\s+', '.', email)
    # Step 2: remove dashes between single letters (spell-out format)
    # e.g. "z-u-b-a-i-r" -> "zubair"
    email = re.sub(r'(?<=[a-z0-9])-(?=[a-z0-9])', '', email)
    # Step 3: remove any remaining spaces
    email = email.replace(' ', '')
    return email
def is_valid_email(email):
    pattern = r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$'
    return re.match(pattern, email) is not None
def resolve_date(date_str):
    """Convert relative dates like 'tomorrow', 'today', or day names to YYYY-MM-DD."""
    date_str = date_str.strip().lower()
    today = date.today()
    if date_str == "today":
        return today.strftime("%Y-%m-%d")
    if date_str == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    # Try parsing day names like "monday", "tuesday", etc.
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, day in enumerate(day_names):
        if day in date_str:
            days_ahead = i - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    # Try common date formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # If nothing matched, return as-is and let downstream error handle it
    return date_str
def resolve_time(time_str):
    """Convert times like '12 p.m.', '3pm', '15:00' to HH:MM 24hr format."""
    time_str = time_str.strip().lower()
    time_str = time_str.replace(".", "").replace(" ", "")
    for fmt in ("%I:%M%p", "%I%p", "%H:%M"):
        try:
            return datetime.strptime(time_str, fmt).strftime("%H:%M")
        except ValueError:
            continue
    # Already in HH:MM
    if re.match(r'^\d{2}:\d{2}$', time_str):
        return time_str
    return time_str
def get_calendar_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('calendar', 'v3', credentials=creds)
def book_meeting(name, email, date_str, time_str, timezone_str="America/New_York"):
    email = clean_email(email)
    if not is_valid_email(email):
        raise ValueError("Invalid email format: " + email)
    # Resolve relative/informal dates and times
    date_str = resolve_date(date_str)
    time_str = resolve_time(time_str)
    service = get_calendar_service()
    tz = pytz.timezone(timezone_str)
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    start = tz.localize(dt)
    end = start + timedelta(minutes=30)
    event = {
        'summary': f'SalesRift Meeting — {name}',
        'description': f'Meeting with {name} ({email})',
        'start': {
            'dateTime': start.isoformat(),
            'timeZone': timezone_str,
        },
        'end': {
            'dateTime': end.isoformat(),
            'timeZone': timezone_str,
        },
        'attendees': [
            {'email': email},
        ],
    }
    result = service.events().insert(
        calendarId=CALENDAR_ID,
        body=event,
        sendUpdates='all'
    ).execute()
    return result.get('htmlLink')