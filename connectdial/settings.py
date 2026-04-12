import os
from pathlib import Path
from datetime import timedelta
from google.oauth2 import service_account
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Security & Core
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = ['192.168.100.107', 'localhost', '127.0.0.1', '10.126.232.156', '192.168.100.4']
AUTH_USER_MODEL = 'users.User'
SITE_ID = 1

# Application definition
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

# settings.py

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'connectdial_db',
        'USER': 'gilly',
        'PASSWORD': 'Iam1@Nitronitro',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

# Static & Media
STATIC_URL = 'static/'
GS_BUCKET_NAME = 'connectdial-bb223.firebasestorage.app'
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

# Authentication & REST
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
)

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 10,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Celery Configuration
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_TIMEZONE = 'UTC'

# connectdial/settings.py
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # --- 1. CORE SOCIAL & ENGAGEMENT TASKS ---
    # These stay frequent as they mostly use your internal database
    'trigger-bot-engagement-every-30m': {
        'task': 'posts.tasks.coordinate_bot_engagement',
        'schedule': crontab(hour='*/12'),  # Every 12 hours
    },
    'bot-social-expansion-hourly': {
        'task': 'posts.tasks.expand_bot_social_graph',
        'schedule': crontab(hour='*/8'), #
        'args': (15,),
    },

    # --- 2. TEXT/IMAGE NEWS SYNC (Staggered every 4 Hours) ---
    # We use different minutes (0, 5, 10, 15...) to avoid hitting the AI API at once
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
                                        
    # --- 3. YOUTUBE SHORTS CONTENT (Staggered every 8-12 Hours) ---
    # Visual content is expensive for quotas; we've moved these to 2-3 times daily.
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

    # Low Priority / International (Every 12 Hours)
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

    # US Secondary & Special (Every 12 Hours)
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

# External API Keys (Loaded from .env)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# Give it 300 seconds (5 minutes) instead of the default 120
GS_DEFAULT_TIMEOUT = 300  
GS_CONNECTION_TIMEOUT = 300

# Optional: Disable the retry mechanism if it's causing loops
GS_BLOB_CHUNK_SIZE = 1024 * 1024 * 5  # 5MB chunks (helps with stability)