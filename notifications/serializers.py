from rest_framework import serializers
from notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source='actor.username', read_only=True)
    actor_fan_badge = serializers.CharField(source='actor.fan_badge', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id',
            'notification_type',
            'actor_username',
            'actor_fan_badge',
            'post',
            'comment',
            'is_read',
            'created_at',
        ]

