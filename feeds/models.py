from django.db import models
from django.conf import settings
from leagues.models import League, Team

User = settings.AUTH_USER_MODEL


class UserFollow(models.Model):
    follower = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='following_users'
    )
    following = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='followers'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'following')

    def __str__(self):
        return f"{self.follower} follows {self.following}"


class TeamFollow(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='followed_teams'
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name='followers'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'team')

    def __str__(self):
        return f"{self.user} follows {self.team}"


class LeagueFollow(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='followed_leagues'
    )
    league = models.ForeignKey(
        League, on_delete=models.CASCADE, related_name='followers'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'league')

    def __str__(self):
        return f"{self.user} follows {self.league}"

