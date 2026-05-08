import os
from pathlib import Path
from datetime import timedelta
from google.oauth2 import service_account
from dotenv import load_dotenv
from celery.schedules import crontab

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ======================
# SECURITY & CORE
# ======================
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = [
    '192.168.100.107', 'localhost', '127.0.0.1', '0.0.0.0',
    '10.126.232.156', '192.168.100.108', '10.199.198.201', '10.199.198.22',
]

AUTH_USER_MODEL = 'users.User'
SITE_ID = 1
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ======================
# APPLICATION DEFINITION
# ======================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',

    # Third Party
    'rest_framework',
    'rest_framework.authtoken',
    'drf_spectacular',
    'dj_rest_auth',
    'dj_rest_auth.registration',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.apple',
    'corsheaders',
    'django_extensions',
    'storages',

    # Local apps
    'users',
    'leagues',
    'posts',
    'notifications',
    'search',
    'trending',
    'short_videos',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'connectdial.urls'
WSGI_APPLICATION = 'connectdial.wsgi.application'

# ======================
# DATABASE
# ======================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'connectdial_db',
        'USER': 'gilly',
        'PASSWORD': os.getenv('DB_PASSWORD', ''),   # ← move to .env, never hardcode
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

# ======================
# TEMPLATES
# ======================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ======================
# STATIC & MEDIA (Google Cloud Storage)
# ======================
STATIC_URL = 'static/'

GS_BUCKET_NAME = 'connect-c894b.firebasestorage.app'
GS_KEY_PATH = os.path.join(BASE_DIR, 'firebase-service-account.json')

if os.path.exists(GS_KEY_PATH):
    GS_CREDENTIALS = service_account.Credentials.from_service_account_file(GS_KEY_PATH)
    STORAGES = {
        "default": {"BACKEND": "storages.backends.gcloud.GoogleCloudStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    MEDIA_URL = f'https://storage.googleapis.com/{GS_BUCKET_NAME}/'
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Google Cloud Storage tweaks
GS_DEFAULT_TIMEOUT = 300
GS_CONNECTION_TIMEOUT = 300
GS_BLOB_CHUNK_SIZE = 1024 * 1024 * 5  # 5MB

# ======================
# CORS
# ⚠️  Lock this down before going to production:
#     CORS_ALLOW_ALL_ORIGINS = False
#     CORS_ALLOWED_ORIGINS = ["https://yourapp.com"]
# ======================
CORS_ALLOW_ALL_ORIGINS = True

# ======================
# AUTHENTICATION BACKENDS
# ======================
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# ======================
# ALLAUTH — headless / API mode
# Your GoogleSignInView bypasses the allauth OAuth redirect entirely and
# validates the id_token directly with google-auth. These settings keep
# allauth happy for account management while staying out of the way for
# social login.
# ======================
ACCOUNT_EMAIL_VERIFICATION = 'none'          # OTP-based verification is handled manually
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_UNIQUE_EMAIL = True

SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_REQUIRED = False         # Google already verified the email
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False   # No extra allauth email step
# SOCIALACCOUNT_LOGIN_ON_GET removed — deprecated and a security risk

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': os.getenv('GOOGLE_CLIENT_ID'),
            'secret': os.getenv('GOOGLE_CLIENT_SECRET'),
            'key': '',
        },
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'FETCH_USERINFO': True,
        # Trust Google's own email verification — no need to re-verify
        'VERIFIED_EMAIL': True,
    }
}

# ======================
# REST FRAMEWORK
# ======================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.TokenAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '300/min',
        'login': '10/min',
        'otp': '5/min',
        'password_reset': '5/min',
    },
}

# ======================
# DJ-REST-AUTH
# ======================
REST_AUTH = {
    'USE_JWT': False,
    'TOKEN_MODEL': 'rest_framework.authtoken.models.Token',
    'OLD_PASSWORD_FIELD_ENABLED': True,
    'REGISTER_SERIALIZER': 'dj_rest_auth.registration.serializers.RegisterSerializer',
}

# ======================
# DRF SPECTACULAR
# ======================
SPECTACULAR_SETTINGS = {
    'TITLE': 'ConnectDial API',
    'DESCRIPTION': 'ConnectDial Backend API Documentation',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'COMPONENT_SPLIT_PATCH': True,
}

# ======================
# EMAIL (Gmail SMTP)
# ======================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@connectdial.com')

# ======================
# CELERY
# ======================
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_TIMEZONE = 'UTC'

CELERY_BEAT_SCHEDULE = {
    # Core tasks
    'trigger-bot-engagement-every-12h': {
        'task': 'posts.tasks.coordinate_bot_engagement',
        'schedule': crontab(hour='*/12'),
    },
    'bot-social-expansion': {
        'task': 'posts.tasks.expand_bot_social_graph',
        'schedule': crontab(hour='*/8'),
        'args': (15,),
    },

    # Sports news sync (staggered)
    'sync-premier-league': {
        'task': 'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=0, hour='*/4'),
        'args': ('Premier League', 5),
    },
    'sync-nba': {
        'task': 'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=5, hour='*/4'),
        'args': ('NBA', 6),
    },
    'sync-champions-league': {
        'task': 'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=10, hour='*/4'),
        'args': ('Champions League', 5),
    },
    'sync-nfl': {
        'task': 'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=15, hour='*/4'),
        'args': ('NFL', 6),
    },
    'sync-la-liga': {
        'task': 'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=20, hour='*/4'),
        'args': ('La Liga', 4),
    },
    'sync-f1': {
        'task': 'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=25, hour='*/4'),
        'args': ('F1', 4),
    },
    'sync-kenya-premier-league': {
        'task': 'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=30, hour='*/4'),
        'args': ('Kenya Premier League', 3),
    },

    # YouTube Shorts (staggered)
    'post-premier-league-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=30, hour='*/8'),
        'args': ('Premier League',),
    },
    'post-nba-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=35, hour='*/8'),
        'args': ('NBA',),
    },
    'post-nfl-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=40, hour='*/8'),
        'args': ('NFL',),
    },
    'post-champions-league-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=45, hour='*/8'),
        'args': ('Champions League',),
    },
    'post-f1-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=50, hour='*/8'),
        'args': ('F1',),
    },
    'post-kenya-premier-league-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=55, hour='*/8'),
        'args': ('Kenya Premier League',),
    },

    # Lower priority leagues (every 12h)
    'post-la-liga-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=0, hour='*/12'),
        'args': ('La Liga',),
    },
    'post-serie-a-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=5, hour='*/12'),
        'args': ('Serie A',),
    },
    'post-bundesliga-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=10, hour='*/12'),
        'args': ('Bundesliga',),
    },
    'post-ligue-1-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=15, hour='*/12'),
        'args': ('Ligue 1',),
    },
    'post-mlb-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=20, hour='*/12'),
        'args': ('MLB',),
    },
    'post-nhl-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=25, hour='*/12'),
        'args': ('NHL',),
    },
    'post-afcon-shorts': {
        'task': 'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=30, hour='*/12'),
        'args': ('Afcon',),
    },
}

# ======================
# EXTERNAL API KEYS
# ======================
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# ======================
# GOOGLE AUTH (used by GoogleSignInView in views.py)
# The mobile app sends an id_token from Google Sign-In SDK.
# GoogleSignInView verifies it directly with google-auth — no redirect needed.
# GOOGLE_CLIENT_ID must exactly match the OAuth client used in your mobile app.
# ======================
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')

# ======================
# OTP SETTINGS
# ======================
OTP_EXPIRY_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = 30

# ======================
# PROXY / AWS CONFIG
# 1 = single ALB, 2 = CloudFront + ALB, 0 = no proxy
# ======================
TRUSTED_PROXY_COUNT = 1
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ======================
# APP NAME (used in 2FA QR code issuer label)
# ======================
APP_NAME = 'ConnectDial'