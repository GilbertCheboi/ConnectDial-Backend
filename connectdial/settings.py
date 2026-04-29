import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account

# Load environment variables from .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────
# Security & Core
# ─────────────────────────────────────────────

SECRET_KEY = os.environ.get('SECRET_KEY')
DEBUG      = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = ['192.168.100.107', '192.168.0.114', 'localhost', '127.0.0.1', '10.126.232.156', '192.168.100.4']

AUTH_USER_MODEL = 'users.User'
SITE_ID         = 1


# ─────────────────────────────────────────────
# Application definition
# ─────────────────────────────────────────────

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
    # rest_framework.authtoken removed — JWT only, no DRF token auth
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
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
    'drf_spectacular',

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

# ─────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────

CORS_ALLOW_ALL_ORIGINS = True
ROOT_URLCONF = 'connectdial.urls'

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

WSGI_APPLICATION = 'connectdial.wsgi.application'

# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ─────────────────────────────────────────────
# Static & Media (Google Cloud Storage)
# ─────────────────────────────────────────────

STATIC_URL     = 'static/'
GS_BUCKET_NAME = 'connectdial-bb223.firebasestorage.app'
GS_KEY_PATH    = os.path.join(BASE_DIR, 'firebase-service-account.json')

if os.path.exists(GS_KEY_PATH):
    GS_CREDENTIALS = service_account.Credentials.from_service_account_file(GS_KEY_PATH)
    STORAGES = {
        "default":     {"BACKEND": "storages.backends.gcloud.GoogleCloudStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    MEDIA_URL = f'https://storage.googleapis.com/{GS_BUCKET_NAME}/'
else:
    MEDIA_URL  = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

GS_DEFAULT_TIMEOUT    = 300
GS_CONNECTION_TIMEOUT = 300
GS_BLOB_CHUNK_SIZE    = 1024 * 1024 * 5   # 5 MB chunks

# ─────────────────────────────────────────────
# Authentication & REST Framework
# ─────────────────────────────────────────────

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
)

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        # TokenAuthentication removed — JWT only
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'DEFAULT_SCHEMA_CLASS':     'drf_spectacular.openapi.AutoSchema',
    'PAGE_SIZE': 10,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon':           '200/day',
        'user':           '2000/day',
        'login':          '5/minute',
        'otp':            '5/minute',
        'password_reset': '3/minute',
    },
}

# ─────────────────────────────────────────────
# JWT (SimpleJWT)
# ─────────────────────────────────────────────

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':    timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME':   timedelta(days=7),
    'AUTH_HEADER_TYPES':        ('Bearer',),
    'ROTATE_REFRESH_TOKENS':    True,   # issue new refresh token on each use
    'BLACKLIST_AFTER_ROTATION': True,   # blacklist old refresh token immediately
    'UPDATE_LAST_LOGIN':        True,
}

# ─────────────────────────────────────────────
# Email (SMTP)
# ─────────────────────────────────────────────

if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST          = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT          = int(os.environ.get('EMAIL_PORT', 587))
    EMAIL_USE_TLS       = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
    EMAIL_HOST_USER     = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@connectdial.com')

# ─────────────────────────────────────────────
# API Documentation (drf-spectacular)
# ─────────────────────────────────────────────

SPECTACULAR_SETTINGS = {
    'TITLE':       'ConnectDial API',
    'DESCRIPTION': 'ConnectDial Backend API Documentation',
    'VERSION':     '1.0.0',
}

# ─────────────────────────────────────────────
# Celery
# ─────────────────────────────────────────────

from celery.schedules import crontab   # noqa: E402

CELERY_BROKER_URL     = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_TIMEZONE       = 'UTC'

CELERY_BEAT_SCHEDULE = {
    # ── Core social & engagement ──────────────────────────────────
    'trigger-bot-engagement-every-12h': {
        'task':     'posts.tasks.coordinate_bot_engagement',
        'schedule': crontab(hour='*/12'),
    },
    'bot-social-expansion-every-8h': {
        'task':     'posts.tasks.expand_bot_social_graph',
        'schedule': crontab(hour='*/8'),
        'args':     (15,),
    },

    # ── Text/image news sync (staggered every 4 hours) ────────────
    'sync-premier-league':       {'task': 'posts.tasks.sync_bots_with_live_sports', 'schedule': crontab(minute=0,  hour='*/4'), 'args': ('Premier League',      5)},
    'sync-nba':                  {'task': 'posts.tasks.sync_bots_with_live_sports', 'schedule': crontab(minute=5,  hour='*/4'), 'args': ('NBA',                 6)},
    'sync-champions-league':     {'task': 'posts.tasks.sync_bots_with_live_sports', 'schedule': crontab(minute=10, hour='*/4'), 'args': ('Champions League',    5)},
    'sync-nfl':                  {'task': 'posts.tasks.sync_bots_with_live_sports', 'schedule': crontab(minute=15, hour='*/4'), 'args': ('NFL',                 6)},
    'sync-la-liga':              {'task': 'posts.tasks.sync_bots_with_live_sports', 'schedule': crontab(minute=20, hour='*/4'), 'args': ('La Liga',             4)},
    'sync-f1':                   {'task': 'posts.tasks.sync_bots_with_live_sports', 'schedule': crontab(minute=25, hour='*/4'), 'args': ('F1',                  4)},
    'sync-kenya-premier-league': {'task': 'posts.tasks.sync_bots_with_live_sports', 'schedule': crontab(minute=30, hour='*/4'), 'args': ('Kenya Premier League', 3)},

    # ── YouTube Shorts (staggered every 8 hours) ──────────────────
    'post-premier-league-shorts':       {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=30, hour='*/8'), 'args': ('Premier League',)},
    'post-nba-shorts':                  {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=35, hour='*/8'), 'args': ('NBA',)},
    'post-nfl-shorts':                  {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=40, hour='*/8'), 'args': ('NFL',)},
    'post-champions-league-shorts':     {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=45, hour='*/8'), 'args': ('Champions League',)},
    'post-f1-shorts':                   {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=50, hour='*/8'), 'args': ('F1',)},
    'post-kenya-premier-league-shorts': {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=55, hour='*/8'), 'args': ('Kenya Premier League',)},

    # ── International / secondary (every 12 hours) ────────────────
    'post-la-liga-shorts':    {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=0,  hour='*/12'), 'args': ('La Liga',)},
    'post-serie-a-shorts':    {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=5,  hour='*/12'), 'args': ('Serie A',)},
    'post-bundesliga-shorts': {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=10, hour='*/12'), 'args': ('Bundesliga',)},
    'post-ligue-1-shorts':    {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=15, hour='*/12'), 'args': ('Ligue 1',)},
    'post-mlb-shorts':        {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=20, hour='*/12'), 'args': ('MLB',)},
    'post-nhl-shorts':        {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=25, hour='*/12'), 'args': ('NHL',)},
    'post-afcon-shorts':      {'task': 'posts.tasks.fetch_and_post_youtube_shorts', 'schedule': crontab(minute=30, hour='*/12'), 'args': ('Afcon',)},
}

# ─────────────────────────────────────────────
# External API keys (from .env)
# ─────────────────────────────────────────────

GEMINI_API_KEY  = os.getenv('GEMINI_API_KEY')
NEWS_API_KEY    = os.getenv('NEWS_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# ─────────────────────────────────────────────
# Google OAuth (django-allauth)
# ─────────────────────────────────────────────

ACCOUNT_EMAIL_VERIFICATION    = 'none'
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_REQUIRED        = True
ACCOUNT_UNIQUE_EMAIL          = True
SOCIALACCOUNT_AUTO_SIGNUP     = True
SOCIALACCOUNT_LOGIN_ON_GET    = True

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': os.getenv('GOOGLE_CLIENT_ID'),
            'secret':    os.getenv('GOOGLE_CLIENT_SECRET'),
            'key':       '',
        },
        'SCOPE':         ['profile', 'email'],
        'AUTH_PARAMS':   {'access_type': 'online'},
        'FETCH_USERINFO': True,
    }
}

REST_AUTH = {
    'USE_JWT':                    True,
    'JWT_AUTH_COOKIE':            None,
    'JWT_AUTH_REFRESH_COOKIE':    None,
    'TOKEN_MODEL':                None,        # ← add this line
    'USER_DETAILS_SERIALIZER':    'users.serializers.UserSerializer',   # controls user payload shape
    'LOGIN_SERIALIZER':           'users.serializers.CustomLoginSerializer',
}