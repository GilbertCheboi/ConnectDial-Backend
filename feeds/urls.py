from django.urls import path
from .views import FollowUserView, FollowTeamView, FollowLeagueView

urlpatterns = [
    path('user/', FollowUserView.as_view(), name='follow-user'),
    path('team/', FollowTeamView.as_view(), name='follow-team'),
    path('league/', FollowLeagueView.as_view(), name='follow-league'),
]

