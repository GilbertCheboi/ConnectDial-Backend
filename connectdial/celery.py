# connectdial/celery.py

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'connectdial.settings')

app = Celery('connectdial')
app.config_from_object('django.conf:settings', namespace='CELERY')

# This is the standard way to find tasks.py in every app
app.autodiscover_tasks()

# 🚀 ADD THIS TO FORCE DISCOVERY IF AUTODISCOVER FAILS
# app.autodiscover_tasks(['notifications', 'posts'])