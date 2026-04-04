import os
import firebase_admin
from firebase_admin import credentials, messaging
from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model

# Ensure Firebase is only initialized once
if not firebase_admin._apps:
    cred_path = os.path.join(settings.BASE_DIR, 'firebase-service-account.json')
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

User = get_user_model()

@shared_task(name="send_push_notification_task")
def send_push_notification_task(user_id, title, message, notification_type=None, object_id=None):
    """
    Sends a push notification via FCM, skipping bots and checking for valid tokens.
    """
    # Local import to prevent circular dependency issues with Profile
    from users.models import Profile 
    
    try:
        user = User.objects.select_related('profile').get(id=user_id)
        
        # 🚀 1. BOT CHECK: Do not attempt to send notifications to bots
        # This prevents the "No FCM token found" log spam you were seeing.
        if hasattr(user, 'profile') and user.profile.is_bot:
            return f"⏭️ Skipped: {user.username} is a bot (no notification needed)."

        # 2. Token Retrieval
        try:
            profile = user.profile
            registration_token = profile.fcm_token
        except Profile.DoesNotExist:
            return f"❌ User {user.username} has no profile attached."

        if not registration_token:
            return f"⚠️ No FCM token found for human user {user.username}. Notification dropped."

        # 🚀 3. Construct Data Payload for React Native Navigation
        # Ensure all values are strings for Firebase compatibility
        data_payload = {
            "type": str(notification_type) if notification_type else "general",
            "id": str(object_id) if object_id else "",
        }

        # 🚀 4. Build the Firebase Message
        message_obj = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=message,
            ),
            token=registration_token,
            data=data_payload, 
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id='default_channel_id',
                    click_action='OPEN_NOTIF_ACTIVITY',
                    sound='default',
                ),
            ),
            # Optional: Add APNS for iOS
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound='default')
                )
            )
        )

        # 5. Send to Firebase
        response = messaging.send(message_obj)
        return f"✅ Sent {notification_type} to {user.username}: {response}"

    except User.DoesNotExist:
        return f"❌ User ID {user_id} not found."
    except Exception as e:
        return f"❌ Firebase Error: {str(e)}"