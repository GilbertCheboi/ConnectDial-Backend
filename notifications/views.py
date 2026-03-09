from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from notifications.models import Notification
from notifications.serializers import NotificationSerializer


from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from notifications.models import DeviceToken
from rest_framework.response import Response
from rest_framework import status


class DeviceTokenRegisterView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        token = request.data.get('token')
        if token:
            DeviceToken.objects.get_or_create(user=request.user, token=token)
            return Response({"status": "registered"})
        return Response({"error": "No token provided"}, status=status.HTTP_400_BAD_REQUEST)




class NotificationListView(ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(
            recipient=self.request.user
        )


from rest_framework.views import APIView
from rest_framework.response import Response

class MarkNotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        Notification.objects.filter(
            id=notification_id,
            recipient=request.user
        ).update(is_read=True)

        return Response({"status": "read"})





