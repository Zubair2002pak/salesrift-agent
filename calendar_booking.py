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
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('calendar', 'v3', credentials=creds)