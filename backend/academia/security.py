import base64
import binascii
import hashlib

from django.core.exceptions import ImproperlyConfigured


def secret_key(value, *, debug=False):
    if not value:
        if debug:
            return 'academia-local-development-only-do-not-use-in-production'
        raise ImproperlyConfigured('Set a private DJANGO_SECRET_KEY before starting production.')
    if debug:
        return value
    if len(set(value)) < 5 or value.startswith('django-insecure-'):
        raise ImproperlyConfigured('Production DJANGO_SECRET_KEY must be a strong random secret.')
    if len(value) < 50:
        # Render generates a base64-encoded 256-bit key (44 characters). Expand it
        # deterministically so Django's deployment check accepts the key length.
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            decoded = b''
        if len(decoded) < 32:
            raise ImproperlyConfigured('Use at least 50 random characters or a base64-encoded 256-bit DJANGO_SECRET_KEY.')
        return hashlib.sha256(decoded).hexdigest()
    return value
