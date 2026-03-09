import firebase_admin
from firebase_admin import messaging, credentials

cred = credentials.Certificate("path/to/serviceAccountKey.json")
firebase_admin.initialize_app(cred)


def send_push_notification(user, title, body, data=None):
    tokens = user.device_tokens.values_list('token', flat=True)
    if not tokens:
        return

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
        tokens=list(tokens)
    )

    response = messaging.send_multicast(message)
    return response

