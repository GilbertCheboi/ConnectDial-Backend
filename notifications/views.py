from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Notification
from .serializers import NotificationSerializer

class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # 🚀 'sender__profile' now works perfectly with select_related
        return Notification.objects.filter(recipient=self.request.user)\
                                   .select_related('sender__profile', 'post')\
                                   .order_by('-created_at')

    def get_serializer_context(self):
        # 🚀 Required to make ProfileSerializer generate absolute image URLs
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        updated_count = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response(
            {'message': f'{updated_count} notifications marked as read.'}, 
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        count = self.get_queryset().filter(is_read=False).count()
        return Response({'unread_count': count}, status=status.HTTP_200_OK)