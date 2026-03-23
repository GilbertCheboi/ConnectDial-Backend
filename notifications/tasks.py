from celery import shared_task
from django.contrib.auth import get_user_model
from firebase_admin import messaging
import firebase_admin
from firebase_admin import credentials
import os
from django.conf import settings

# Ensure Firebase is only initialized once at the module level
if not firebase_admin._apps:
    cred_path = os.path.join(settings.BASE_DIR, 'firebase-service-account.json')
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

User = get_user_model()

@shared_task
def send_push_notification_task(user_id, title, message, notification_type=None, object_id=None):
    """
    Sends a push notification with a data payload for app navigation.
    """
    # 🚀 RESTORED: Local import to prevent circular dependency
    from users.models import Profile 
    
    try:
        user = User.objects.get(id=user_id)
        
        # Access fcm_token via the profile relationship
        try:
            profile = user.profile
            registration_token = profile.fcm_token
        except Profile.DoesNotExist:
            return f"❌ User {user.username} has no profile attached."

        if not registration_token:
            return f"⚠️ No FCM token found in profile for {user.username}"

        # 🚀 1. Construct the Data Payload
        # These keys ('type' and 'id') must match what your React Native 
        # listeners are looking for.
        data_payload = {
            "type": str(notification_type) if notification_type else "general",
            "id": str(object_id) if object_id else "",
        }

        # 🚀 2. Build the Message
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
        )

        # 3. Send to Firebase
        response = messaging.send(message_obj)
        print(f"✅ Successfully sent {notification_type} message to {user.username}: {response}")
        return response

    except User.DoesNotExist:
        print(f"❌ User ID {user_id} not found")
        return None
    except Exception as e:
        print(f"❌ Firebase Error: {str(e)}")
        return None