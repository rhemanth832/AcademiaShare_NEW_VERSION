import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from .security import secret_key

BASE_DIR = Path(__file__).resolve().parent.parent
PRODUCTION = os.environ.get('DJANGO_ENV') == 'production'
DEBUG = os.environ.get('DJANGO_DEBUG', '0' if PRODUCTION else '1') == '1'
SECRET_KEY = secret_key(os.environ.get('DJANGO_SECRET_KEY'), debug=DEBUG)

DATA_ROOT = Path(os.environ.get('ACADEMIA_DATA_DIR', str(BASE_DIR))).resolve()
if PRODUCTION and not os.environ.get('ACADEMIA_DATA_DIR'):
    raise ImproperlyConfigured('Set ACADEMIA_DATA_DIR to your mounted persistent storage directory.')
RENDER_HOST = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip()
ALLOWED_HOSTS = [v.strip() for v in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1' + (',testserver' if DEBUG else '')).split(',') if v.strip()]
if RENDER_HOST and RENDER_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_HOST)
if PRODUCTION and not any(v not in ('localhost', '127.0.0.1') for v in ALLOWED_HOSTS):
    raise ImproperlyConfigured('Configure DJANGO_ALLOWED_HOSTS or RENDER_EXTERNAL_HOSTNAME for your live hostname.')
if not DEBUG and '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('Use your exact public hostname instead of a wildcard ALLOWED_HOSTS.')
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.environ.get('DJANGO_CSRF_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173' if DEBUG else '').split(',') if v.strip()]
if RENDER_HOST:
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_HOST}')

INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','core.apps.CoreConfig']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','whitenoise.middleware.WhiteNoiseMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'academia.urls'
WSGI_APPLICATION = 'academia.wsgi.application'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':DATA_ROOT/'db.sqlite3','CONN_MAX_AGE':60,'OPTIONS':{'timeout':30,'transaction_mode':'IMMEDIATE'}}}
AUTH_USER_MODEL = 'core.User'
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
FRONTEND_DIST = BASE_DIR.parent/'dist'
STATIC_URL = '/assets/'
STATIC_ROOT = BASE_DIR/'staticfiles'
STATICFILES_DIRS = [FRONTEND_DIST/'assets'] if (FRONTEND_DIST/'assets').exists() else []
STORAGES = {'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
MEDIA_ROOT = DATA_ROOT/'media'
BACKUP_ROOT = DATA_ROOT/'backups'
MAX_RESOURCE_SIZE = 25*1024*1024
USER_STORAGE_LIMIT = 500*1024*1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 27*1024*1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2*1024*1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 60*60*24*7
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
X_FRAME_OPTIONS = 'DENY'
CACHES = {'default': {'BACKEND':'django.core.cache.backends.db.DatabaseCache','LOCATION':'academia_cache'}} if PRODUCTION else {'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}}
CSRF_FAILURE_VIEW = 'core.views.csrf_failure'
SCHEDULER_REQUIRED = os.environ.get('ACADEMIA_SCHEDULER_REQUIRED', '1' if PRODUCTION else '0') == '1'

# Enable only behind a hosting proxy which overwrites client forwarding headers.
if os.environ.get('DJANGO_TRUST_PROXY') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

LOGGING = {'version':1,'disable_existing_loggers':False,'handlers':{'console':{'class':'logging.StreamHandler'}},'root':{'handlers':['console'],'level':'INFO'}}
