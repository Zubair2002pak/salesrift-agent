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
    email = re.sub(r'\s+at\s+', '@', email)
    email = re.sub(r'\s+dot\s+', '.', email)
    email = re.sub(r'(?<=[a-z0-9])-(?=[a-z0-9])', '', email)
    email = email.replace(' ', '')
    return email

def is_valid_email(email):
    pattern = r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$'
    return re.match(pattern, email) is not None

def resolve_date(date_str):
    date_str = date_str.strip().lower()
    today = date.today()
    if date_str == "today":
        return today.strftime("%Y-%m-%d")
    if date_str == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, day in enumerate(day_names):
        if day in date_str:
            days_ahead = i - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str

def resolve_time(time_str):
    time_str = time_str.strip().lower()
    time_str = time_str.replace(".", "").replace(" ", "")
    for fmt in ("%I:%M%p", "%I%p", "%H:%M"):
        try:
            return datetime.strptime(time_str, fmt).strftime("%H:%M")
        except ValueError:
            continue
    if re.match(r'^\d{2}:\d{2}$', time_str):
        return time_str
    return time_str

def get_calendar_service():
    creds = None
    token_b64 = os.environ.get('GOOGLE_TOKEN_PICKLE')
    if token_b64:
        import base64, io
        creds = pickle.load(io.BytesIO(base64.b64decode(token_b64)))
    elif os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            import json, tempfile
            creds_json = os.environ.get('GOOGLE_CREDENTIALS')
            if creds_json:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                    f.write(creds_json)
                    tmp_path = f.name
                flow = InstalledAppFlow.from_client_secrets_file(tmp_path, SCOPES)
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('calendar', 'v3', credentials=creds)

def book_meeting(name, email, date_str, time_str, timezone_str="America/New_York"):
    email = clean_email(email)
    if not is_valid_email(email):
        raise ValueError("Invalid email format: " + email)
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
        'conferenceData': {
            'createRequest': {
                'requestId': 'salesrift-' + name.replace(' ', '-').lower(),
                'conferenceSolutionKey': {'type': 'hangoutsMeet'}
            }
        },
    }
    result = service.events().insert(
        calendarId=CALENDAR_ID,
        body=event,
        sendUpdates='all',
        conferenceDataVersion=1
    ).execute()
    return result.get('htmlLink')