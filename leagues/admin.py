from django.contrib import admin
from .models import League, Team

@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    # Displays these columns in the list view
    list_display = ('id', 'name', 'abbreviation')
    # Adds a search bar for both the name and the manual ID
    search_fields = ('id', 'name', 'abbreviation')
    # Ensures the ID is the first thing you see
    ordering = ('id',)

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'league')
    search_fields = ('id', 'name', 'league__name')
    # Filters on the right side to drill down by League
    list_filter = ('league',)
    ordering = ('id',)