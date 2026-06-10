from google_auth_oauthlib.flow import InstalledAppFlow

# The exact scope you set up in the Google Console
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

def main():
    # This points to the JSON file you just downloaded and renamed
    flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
    
    # This will open your web browser and ask you to log in
    creds = flow.run_local_server(port=0)
    
    print("\n✅ Success! Here is your Refresh Token:\n")
    print(creds.refresh_token)

if __name__ == '__main__':
    main()


#Place client_secret.json in the same directory as this script, then run it. After you authenticate with your Google account, it will print out the Refresh Token you need to put in your .env file.