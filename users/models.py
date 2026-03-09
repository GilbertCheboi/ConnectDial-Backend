from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):

    AUTH_PROVIDERS = (
        ('email', 'Email'),
        ('google', 'Google'),
        ('apple', 'Apple'),
        ('facebook', 'Facebook'),
    )

    auth_provider = models.CharField(
        max_length=20,
        choices=AUTH_PROVIDERS,
        default='email'
    )

    favorite_team = models.ForeignKey(
        'leagues.Team',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='favorite_users'
    )

    favorite_league = models.ForeignKey(
        'leagues.League',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='favorite_users'
    )

    fan_badge = models.CharField(
        max_length=50,
        default='Awaiting Partnership'
    )

    def __str__(self):
        return self.username



class FanPreference(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fan_preferences"
    )

    league = models.ForeignKey(
        'leagues.League',
        on_delete=models.CASCADE,
        related_name="league_fans"
    )

    team = models.ForeignKey(
        'leagues.Team',
        on_delete=models.CASCADE,
        related_name="team_fans"
    )

    followed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'league')

    def __str__(self):
        return f"{self.user.username} - {self.team.name}"