from rest_framework import serializers
from .models import Notification
from django.contrib.humanize.templatetags.humanize import naturaltime
from users.serializers import ProfileSerializer 

class NotificationSerializer(serializers.ModelSerializer):
    # 🚀 Simple and clean now that we use OneToOneField
    sender_profile = ProfileSerializer(source='sender.profile', read_only=True)
    time_ago = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 
            'notification_type', 
            'sender_profile', 
            'post', 
            'is_read', 
            'time_ago'
        ]

    def get_time_ago(self, obj):
        return naturaltime(obj.created_at)