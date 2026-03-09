from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from .utils import get_short_video_feed
from .serializers import ShortVideoSerializer

class ShortVideoFeedView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ShortVideoSerializer

    def get_queryset(self):
        return get_short_video_feed(self.request.user)

