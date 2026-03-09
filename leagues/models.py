from django.db import models

class League(models.Model):
    """
    Represents a sports league, e.g., NBA, EPL
    """
    name = models.CharField(max_length=100, unique=True)
    abbreviation = models.CharField(max_length=10, blank=True)
    logo = models.ImageField(upload_to='league_logos/', blank=True, null=True)

    def __str__(self):
        return self.name



class Team(models.Model):
    """
    Represents a sports team belonging to a league
    """
    name = models.CharField(max_length=100, unique=True)
    league = models.ForeignKey(
        League,
        on_delete=models.CASCADE,
        related_name='teams'
    )
    logo = models.ImageField(upload_to='team_logos/', blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.league.abbreviation})"

