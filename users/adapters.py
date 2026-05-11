from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from django.conf import settings


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        user.auth_provider = sociallogin.account.provider
        user.save()
        return user


class GoogleIdTokenAdapter(GoogleOAuth2Adapter):
    """
    Accepts a Google id_token from React Native instead of an access_token.
    Verifies it locally using Google's public keys — no extra HTTP round-trip.
    """

    def complete_login(self, request, app, token, **kwargs):
        raw_id_token = request.data.get('id_token', '').strip()

        try:
            idinfo = google_id_token.verify_oauth2_token(
                raw_id_token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except ValueError as e:
            raise Exception(f'Invalid Google id_token: {e}')

        if not idinfo.get('email_verified'):
            raise Exception('Google email not verified')

        extra_data = {
            'sub':            idinfo['sub'],
            'email':          idinfo['email'],
            'given_name':     idinfo.get('given_name', ''),
            'family_name':    idinfo.get('family_name', ''),
            'picture':        idinfo.get('picture', ''),
            'email_verified': True,
        }

        return self.get_provider().sociallogin_from_response(request, extra_data)
