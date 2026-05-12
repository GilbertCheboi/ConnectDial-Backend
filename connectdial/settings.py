import os
from pathlib import Path
from datetime import timedelta
from google.oauth2 import service_account
from dotenv import load_dotenv
from celery.schedules import crontab

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ======================
# SECURITY & CORE
# ======================
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
DEBUG = os.getenv('DEBUG', 'False') == 'True'

# ✅ FIX: ALLOWED_HOSTS takes plain hostnames only — no http:// or https:// prefix.
# Your original had 'http://16.16.98.131' and 'https://16.16.98.131' which Django
# ignores / rejects, causing DisallowedHost errors in production.
ALLOWED_HOSTS = [
    '192.168.100.107',
    'localhost',
    '127.0.0.1',
    '0.0.0.0',
    '10.126.232.156',
    '192.168.100.108',
    '10.199.198.201',
    '10.199.198.22',
   # plain IP — no scheme
    'dev.connectdial.com',
    '51.20.182.163',
    '*',
]

AUTH_USER_MODEL = 'users.User'
SITE_ID = 1

# ✅ GOOGLE_CLIENT_ID — Web OAuth 2.0 Client ID from Google Cloud Console.
# Must match webClientId in the React Native app's configureGoogleSignin().
GOOGLE_CLIENT_ID         = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_ANDROID_CLIENT_ID = os.getenv('GOOGLE_ANDROID_CLIENT_ID', '')  # optional
GOOGLE_IOS_CLIENT_ID     = os.getenv('GOOGLE_IOS_CLIENT_ID', '')      # optional

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
        'ENGINE':   'django.db.backends.postgresql',
        'NAME':     'connectdial_db',
        'USER':     'gilly',
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST':     os.getenv('DB_HOST', 'localhost'),
        'PORT':     os.getenv('DB_PORT', '5432'),
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
# STATIC & MEDIA — Google Cloud Storage (Firebase Storage bucket)
# ======================
#
# 'connect-c894b.firebasestorage.app' is a Firebase Storage bucket backed by GCS.
# django-storages accesses it via the standard GCS JSON API using your service account.
#
# REQUIRED on your Firebase/GCS bucket for the service account:
#   IAM role: roles/storage.objectAdmin  (Storage Object Admin)
#
# With GS_QUERYSTRING_AUTH = False (below), files must also be publicly readable.
# In GCS Console → Bucket → Permissions → Add:
#   Principal: allUsers
#   Role:      Storage Object Viewer
#
# Public URL format:
#   https://storage.googleapis.com/connect-c894b.firebasestorage.app/<filename>
# ======================

STATIC_URL  = 'static/'
GS_BUCKET_NAME = 'connect-c894b.firebasestorage.app'
GS_KEY_PATH    = os.path.join(BASE_DIR, 'firebase-service-account.json')

if os.path.exists(GS_KEY_PATH):
    GS_CREDENTIALS = service_account.Credentials.from_service_account_file(GS_KEY_PATH)

    STORAGES = {
        "default":     {"BACKEND": "storages.backends.gcloud.GoogleCloudStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

    MEDIA_URL = f'https://storage.googleapis.com/{GS_BUCKET_NAME}/'

    # ✅ FIX: Without this, every media URL is a signed URL that expires in ~1 hour.
    # Profile images and any stored file will return 403 after expiry.
    # Setting False makes URLs permanent public links (bucket must allow allUsers read).
    GS_QUERYSTRING_AUTH = False

    # ✅ FIX: Without this, two uploads with the same filename silently overwrite each other.
    # django-storages will append a unique suffix to avoid collisions.
    GS_FILE_OVERWRITE = False

    # ✅ Cache-Control so browsers and CDNs cache media files for 24h
    GS_OBJECT_PARAMETERS = {
        'cache_control': 'public, max-age=86400',
    }

else:
    # Fallback: local filesystem (no firebase-service-account.json present)
    MEDIA_URL  = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# GCS connection tuning
GS_DEFAULT_TIMEOUT    = 300
GS_CONNECTION_TIMEOUT = 300
GS_BLOB_CHUNK_SIZE    = 1024 * 1024 * 5  # 5 MB

# ======================
# CORS
# ======================
CORS_ALLOWED_ORIGINS = [
    'http://51.20.182.163',
    'https://51.20.182.163',
    'http://dev.connectdial.com',
    'https://dev.connectdial.com',
]

CSRF_TRUSTED_ORIGINS = [
    'http://51.20.182.163',
    'https://51.20.182.163',
    'http://dev.connectdial.com',
    'https://dev.connectdial.com',
]

# ======================
# AUTHENTICATION BACKENDS
# ======================
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# ======================
# ALLAUTH — headless / API mode
# GoogleSignInView verifies id_tokens directly — no OAuth redirect used.
# ======================
ACCOUNT_EMAIL_VERIFICATION    = 'none'    # OTP-based verification handled manually
ACCOUNT_EMAIL_REQUIRED        = True
ACCOUNT_UNIQUE_EMAIL          = True
ACCOUNT_USERNAME_REQUIRED     = False
ACCOUNT_AUTHENTICATION_METHOD = 'email'

SOCIALACCOUNT_AUTO_SIGNUP                       = True
SOCIALACCOUNT_EMAIL_REQUIRED                    = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION              = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
# ✅ FIX: SOCIALACCOUNT_LOGIN_ON_GET = True removed — it's a CSRF security risk
# that allows GET requests to complete social login without a CSRF token.

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': os.getenv('GOOGLE_CLIENT_ID'),
            'secret':    os.getenv('GOOGLE_CLIENT_SECRET'),
            'key':       '',
        },
        'SCOPE':          ['profile', 'email'],
        'AUTH_PARAMS':    {'access_type': 'online'},
        'FETCH_USERINFO': True,
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
    'DEFAULT_SCHEMA_CLASS':        'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS':    'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon':           '60/min',
        'user':           '300/min',
        'login':          '10/min',
        'otp':            '5/min',
        'password_reset': '5/min',
    },
}

# ======================
# DJ-REST-AUTH
# ======================
REST_AUTH = {
    'USE_JWT':                   False,
    'TOKEN_MODEL':               'rest_framework.authtoken.models.Token',
    'OLD_PASSWORD_FIELD_ENABLED': True,
    'REGISTER_SERIALIZER':       'dj_rest_auth.registration.serializers.RegisterSerializer',
}

# ======================
# DRF SPECTACULAR
# ======================
SPECTACULAR_SETTINGS = {
    'TITLE':                'ConnectDial API',
    'DESCRIPTION':          'ConnectDial Backend API Documentation',
    'VERSION':              '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'COMPONENT_SPLIT_PATCH':   True,
}

# ======================
# EMAIL (Gmail SMTP)
# ======================
EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST          = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT          = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS       = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER     = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL  = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@connectdial.com')

# ======================
# CELERY
# ======================
CELERY_BROKER_URL     = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_TIMEZONE       = 'UTC'

CELERY_BEAT_SCHEDULE = {
    'trigger-bot-engagement-every-12h': {
        'task':     'posts.tasks.coordinate_bot_engagement',
        'schedule': crontab(hour='*/12'),
    },
    'check-unread-every-2-minutes': {
        'task': 'notifications.tasks.check_unread_notifications_periodic',
        'schedule': 120.0,  # Time in seconds (2 minutes)
    },
    'bot-social-expansion': {
        'task':     'posts.tasks.expand_bot_social_graph',
        'schedule': crontab(hour='*/8'),
        'args':     (15,),
    },
    'sync-premier-league': {
        'task':     'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=0, hour='*/4'),
        'args':     ('Premier League', 5),
    },
    'sync-nba': {
        'task':     'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=5, hour='*/4'),
        'args':     ('NBA', 6),
    },
    'sync-champions-league': {
        'task':     'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=10, hour='*/4'),
        'args':     ('Champions League', 5),
    },
    'sync-nfl': {
        'task':     'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=15, hour='*/4'),
        'args':     ('NFL', 6),
    },
    'sync-la-liga': {
        'task':     'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=20, hour='*/4'),
        'args':     ('La Liga', 4),
    },
    'sync-f1': {
        'task':     'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=25, hour='*/4'),
        'args':     ('F1', 4),
    },
    'sync-kenya-premier-league': {
        'task':     'posts.tasks.sync_bots_with_live_sports',
        'schedule': crontab(minute=30, hour='*/4'),
        'args':     ('Kenya Premier League', 3),
    },
    'post-premier-league-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=30, hour='*/8'),
        'args':     ('Premier League',),
    },
    'post-nba-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=35, hour='*/8'),
        'args':     ('NBA',),
    },
    'post-nfl-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=40, hour='*/8'),
        'args':     ('NFL',),
    },
    'post-champions-league-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=45, hour='*/8'),
        'args':     ('Champions League',),
    },
    'post-f1-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=50, hour='*/8'),
        'args':     ('F1',),
    },
    'post-kenya-premier-league-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=55, hour='*/8'),
        'args':     ('Kenya Premier League',),
    },
    'post-la-liga-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=0, hour='*/12'),
        'args':     ('La Liga',),
    },
    'post-serie-a-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=5, hour='*/12'),
        'args':     ('Serie A',),
    },
    'post-bundesliga-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=10, hour='*/12'),
        'args':     ('Bundesliga',),
    },
    'post-ligue-1-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=15, hour='*/12'),
        'args':     ('Ligue 1',),
    },
    'post-mlb-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=20, hour='*/12'),
        'args':     ('MLB',),
    },
    'post-nhl-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=25, hour='*/12'),
        'args':     ('NHL',),
    },
    'post-afcon-shorts': {
        'task':     'posts.tasks.fetch_and_post_youtube_shorts',
        'schedule': crontab(minute=30, hour='*/12'),
        'args':     ('Afcon',),
    },
}

# ======================
# EXTERNAL API KEYS
# ======================
GEMINI_API_KEY  = os.getenv('GEMINI_API_KEY')
NEWS_API_KEY    = os.getenv('NEWS_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# ======================
# OTP SETTINGS
# ======================
OTP_EXPIRY_SECONDS  = 300
OTP_MAX_ATTEMPTS    = 5
OTP_RESEND_COOLDOWN = 30

# ======================
# PROXY / AWS CONFIG
# ======================
TRUSTED_PROXY_COUNT     = 1
USE_X_FORWARDED_HOST    = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ======================
# APP NAME
# ======================
APP_NAME = 'ConnectDial'
