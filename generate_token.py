from google_auth_oauthlib.flow import InstalledAppFlow
import os

SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']

def main():
    creds = None
    if not os.path.exists('client_secret.json'):
        print("credentials.json not found! Download it from Google Cloud Console.")
        return
    flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
    creds = flow.run_local_server(port=0)
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
    print("token.json has been generated.")

if __name__ == '__main__':
    main()