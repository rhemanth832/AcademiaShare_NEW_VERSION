"""Membership-protected call scheduling with external conferencing providers."""
import secrets
from urllib.parse import urlsplit
from django.core.validators import URLValidator
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from .models import VideoCall
from .views import endpoint, payload, text, teacher, course, APIError, notify, activity
from .exams import date_value


def call_json(call, u):
    return {'id': call.id, 'course': call.course_id, 'title': call.title,
            'description': call.description, 'starts_at': call.starts_at, 'status': call.status,
            'started_at': call.started_at, 'ended_at': call.ended_at,
            'provider': 'Jitsi Meet' if urlsplit(call.join_url).hostname == 'meet.jit.si' else 'External meeting',
            'created_at': call.created_at}


@endpoint(('POST',))
@transaction.atomic
def create_call(r):
    teacher(r.user)
    d = payload(r)
    c = course(r.user, d.get('course'), True)
    starts = date_value(d, 'starts_at')
    url = text(d, 'join_url', 1000, False)
    if url:
        URLValidator(schemes=['https'])(url)
        parts = urlsplit(url)
        if parts.username or parts.password:
            raise APIError('Use a meeting link without embedded credentials.')
    else:
        url = f'https://meet.jit.si/AcademiaShare-{secrets.token_hex(20)}'
    live = d.get('start_now') is True
    call = VideoCall.objects.create(course=c, title=text(d, 'title'), description=text(d, 'description', 4000, False),
        starts_at=timezone.now() if live else starts, join_url=url, status='live' if live else 'scheduled',
        started_at=timezone.now() if live else None)
    notify(c, f'{"Live now" if live else "Video class scheduled"}: {call.title}', r.user, kind='call', target=f'call:{call.id}')
    activity(r.user, f'{"started" if live else "scheduled"} the video class “{call.title}”', c)
    return JsonResponse(call_json(call, r.user), status=201)


@endpoint(('POST',))
@transaction.atomic
def update_call(r, pk, action):
    call = VideoCall.objects.select_related('course').filter(pk=pk).first()
    if not call:
        raise APIError('Video class not found.', 404)
    c = course(r.user, call.course_id, True)
    if action == 'start':
        if call.status == 'ended':
            raise APIError('This video class has ended. Create a new session.')
        if call.status != 'live':
            call.status, call.started_at = 'live', timezone.now()
            call.save(update_fields=['status', 'started_at'])
            notify(c, f'Live now: {call.title}. Join your class video call.', r.user, kind='call', target=f'call:{call.id}')
    elif action == 'end':
        if call.status != 'ended':
            call.status, call.ended_at = 'ended', timezone.now()
            call.save(update_fields=['status', 'ended_at'])
            notify(c, f'Video class ended: {call.title}', r.user, kind='call', target=f'call:{call.id}')
    else:
        raise APIError('Unknown video action.', 404)
    return JsonResponse(call_json(call, r.user))


@endpoint(('POST',))
def join_call(r, pk):
    call = VideoCall.objects.select_related('course').filter(pk=pk).first()
    if not call:
        raise APIError('Video class not found.', 404)
    course(r.user, call.course_id)
    if call.status != 'live':
        raise APIError('Join when your teacher starts this video class.')
    return JsonResponse({'join_url': call.join_url, 'call': call_json(call, r.user)})
