# notifications/utils.py
import firebase_admin
from firebase_admin import credentials, messaging
import os
from django.conf import settings

# Initialize Firebase Admin SDK
path_to_key = os.path.join(settings.BASE_DIR, 'firebase-service-account.json')

if not firebase_admin._apps:
    cred = credentials.Certificate(path_to_key)
    firebase_admin.initialize_app(cred)

def send_fcm_notification(token, title, body):
    """
    Sends a message to a specific device via FCM.
    """
    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        token=token,
        android=messaging.AndroidConfig(
            priority='high',
            notification=messaging.AndroidNotification(
                channel_id='default_channel_id', # Matches your AndroidManifest.xml
                click_action='OPEN_NOTIF_ACTIVITY', # Optional: for deep linking
            ),
        ),
    )

    try:
        response = messaging.send(message)
        return response
    except Exception as e:
        print(f"❌ Firebase Error: {e}")
        return None