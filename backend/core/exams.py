"""Timed MCQ exams. The database, never a browser score or clock, is authoritative."""
import uuid
from datetime import timedelta
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import Exam, ExamAttempt, Notification, Course
from .views import endpoint, payload, text, teacher, course, ids, uj, APIError, notify, activity


def date_value(d, key):
    value = parse_datetime(d.get(key, ''))
    if not value or timezone.is_naive(value):
        raise APIError(f'{key.replace("_", " ").capitalize()} needs a date, time, and timezone.')
    return value


def positive_int(value, label, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise APIError(f'{label} must be a whole number between 1 and {maximum}.')
    return value


def validate_questions(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
        raise APIError('Add between 1 and 100 questions.')
    result = []
    for raw_q in raw:
        if not isinstance(raw_q, dict):
            raise APIError('Each question must be an object.')
        prompt = text(raw_q, 'text', 3000)
        options = raw_q.get('options')
        if not isinstance(options, list) or not 2 <= len(options) <= 6:
            raise APIError('Each question needs 2 to 6 answer choices.')
        if any(not isinstance(o, str) or not o.strip() or len(o) > 1000 for o in options):
            raise APIError('Write a nonempty answer of at most 1000 characters in each choice.')
        options = [o.strip() for o in options]
        if len(set(o.casefold() for o in options)) != len(options):
            raise APIError('Answer choices must be different from one another.')
        correct = raw_q.get('correct')
        if isinstance(correct, bool) or not isinstance(correct, int) or not 0 <= correct < len(options):
            raise APIError('Select one correct answer for each question.')
        result.append({'id': uuid.uuid4().hex, 'text': prompt, 'options': options,
                       'correct': correct, 'points': positive_int(raw_q.get('points', 1), 'Question points', 100),
                       'explanation': text(raw_q, 'explanation', 3000, False)})
    return result


def get_exam(u, pk):
    exam = Exam.objects.select_related('course__teacher').filter(pk=pk).first()
    if not exam:
        raise APIError('Exam not found.', 404)
    course(u, exam.course_id)
    if u.id != exam.course.teacher_id and timezone.now() < exam.appears_at:
        raise APIError('This exam is not available yet.', 404)
    return exam


def results_available(exam, now=None):
    return exam.results_mode == 'immediate' or (now or timezone.now()) >= exam.deadline


def max_score(exam):
    return sum(q['points'] for q in exam.questions)


@transaction.atomic
def finish_attempt(attempt, completion, now=None):
    """Conditional update prevents duplicate marks/notifications for racing submissions."""
    attempt.refresh_from_db()
    if attempt.submitted_at:
        return attempt
    now = now or timezone.now()
    correct = wrong = unanswered = score = 0
    for question in attempt.exam.questions:
        answer = attempt.answers.get(question['id'])
        if answer is None:
            unanswered += 1
        elif answer == question['correct']:
            correct += 1
            score += question['points']
        else:
            wrong += 1
    changed = ExamAttempt.objects.filter(pk=attempt.pk, submitted_at__isnull=True).update(
        submitted_at=min(now, attempt.expires_at), completion=completion, score=score,
        correct=correct, wrong=wrong, unanswered=unanswered)
    if changed:
        exam = attempt.exam
        Notification.objects.create(user_id=exam.course.teacher_id, kind='exam', target=f'exam:{exam.id}',
            text=f'{attempt.student.first_name or attempt.student.username} completed {exam.title}.'[:255])
        Notification.objects.create(user_id=attempt.student_id, kind='result', target=f'exam:{exam.id}',
            text=f'Results are ready: {exam.title}.'[:255],
            available_at=now if results_available(exam, now) else exam.deadline)
    attempt.refresh_from_db()
    return attempt


def finalize_expired(exam_ids=None, student=None, limit=None):
    attempts = ExamAttempt.objects.filter(submitted_at__isnull=True, expires_at__lte=timezone.now())
    if exam_ids is not None:
        attempts = attempts.filter(exam_id__in=exam_ids)
    if student is not None:
        attempts = attempts.filter(student=student)
    attempts=attempts.select_related('exam__course','student').order_by('expires_at')
    if limit is not None:attempts=attempts[:limit]
    for attempt in attempts:
        finish_attempt(attempt, 'timeout')


def attempt_json(attempt, viewer):
    if not attempt:
        return None
    exam = attempt.exam
    can_review = bool(attempt.submitted_at) and (viewer.id == exam.course.teacher_id or results_available(exam))
    result = {'id': attempt.id, 'started_at': attempt.started_at, 'expires_at': attempt.expires_at,
              'submitted_at': attempt.submitted_at, 'completion': attempt.completion,
              'answers': attempt.answers, 'results_available': can_review}
    if can_review:
        result.update(score=attempt.score, correct=attempt.correct, wrong=attempt.wrong, unanswered=attempt.unanswered,
                      total_points=max_score(exam), review=[{**q, 'answer': attempt.answers.get(q['id'])} for q in exam.questions])
    return result


def exam_json(exam, u):
    mine = exam.attempts.filter(student=u).first()
    return {'id': exam.id, 'course': exam.course_id, 'title': exam.title, 'description': exam.description,
            'appears_at': exam.appears_at, 'starts_at': exam.starts_at, 'deadline': exam.deadline,
            'duration_minutes': exam.duration_minutes, 'results_mode': exam.results_mode,
            'question_count': len(exam.questions), 'points': max_score(exam), 'created_at': exam.created_at,
            'my_attempt': attempt_json(mine, u),
            'submission_count': exam.attempts.filter(submitted_at__isnull=False).count() if u.id == exam.course.teacher_id else None}


@endpoint(('POST',))
@transaction.atomic
def create_exam(r):
    teacher(r.user)
    d = payload(r)
    c = course(r.user, d.get('course'), True)
    appears, starts, deadline = (date_value(d, k) for k in ('appears_at', 'starts_at', 'deadline'))
    if not appears <= starts < deadline or deadline <= timezone.now():
        raise APIError('Appearance must be at or before start, and the deadline must be in the future after start.')
    if d.get('results_mode', 'after_deadline') not in ('after_deadline', 'immediate'):
        raise APIError('Choose when students can see their results.')
    exam = Exam.objects.create(course=c, title=text(d, 'title'), description=text(d, 'description', 10000, False),
        appears_at=appears, starts_at=starts, deadline=deadline,
        duration_minutes=positive_int(d.get('duration_minutes', 60), 'Duration in minutes', 480),
        results_mode=d.get('results_mode', 'after_deadline'), questions=validate_questions(d.get('questions')))
    notify(c, f'New MCQ exam: {exam.title}', r.user, kind='exam', target=f'exam:{exam.id}', available_at=appears)
    notify(c, f'Exam opens now: {exam.title}', r.user, kind='exam', target=f'exam:{exam.id}', available_at=starts)
    activity(r.user, f'created the MCQ exam “{exam.title}”', c if appears <= timezone.now() else None)
    return JsonResponse(exam_json(exam, r.user), status=201)


@endpoint()
def exam_detail(r, pk):
    exam = get_exam(r.user, pk)
    finalize_expired([pk])
    result = exam_json(exam, r.user)
    mine = result['my_attempt']
    # No question content before starting, and no answer key before results release.
    if r.user.id == exam.course.teacher_id:
        result['questions'] = exam.questions
    elif mine:
        result['questions'] = [{k: v for k, v in q.items() if k not in ('correct', 'explanation')} for q in exam.questions]
    return JsonResponse({'exam': result, 'server_now': timezone.now()})


@endpoint(('POST',))
@transaction.atomic
def start_exam(r, pk):
    exam = get_exam(r.user, pk)
    if r.user.role != 'student':
        raise APIError('Only enrolled students can take exams.', 403)
    finalize_expired([pk], r.user)
    attempt = exam.attempts.filter(student=r.user).first()
    now = timezone.now()
    if not attempt:
        if now < exam.starts_at:
            raise APIError('This exam has not started yet.')
        if now >= exam.deadline:
            raise APIError('The exam deadline has passed.')
        attempt, _ = ExamAttempt.objects.get_or_create(exam=exam, student=r.user, defaults={
            'started_at': now, 'expires_at': min(now + timedelta(minutes=exam.duration_minutes), exam.deadline)})
    return JsonResponse({'attempt': attempt_json(attempt, r.user), 'server_now': timezone.now()})


def validate_answers(exam, raw):
    if not isinstance(raw, dict):
        raise APIError('Answers must be a question-to-choice object.')
    questions = {q['id']: q for q in exam.questions}
    for qid, answer in raw.items():
        if qid not in questions or isinstance(answer, bool) or not isinstance(answer, int) or not 0 <= answer < len(questions[qid]['options']):
            raise APIError('An answer refers to an invalid question or choice.')
    return raw


@endpoint(('PATCH', 'POST'))
@transaction.atomic
def answer_exam(r, pk):
    exam = get_exam(r.user, pk)
    attempt = exam.attempts.select_for_update().filter(student=r.user).first()
    if not attempt:
        raise APIError('Start this exam before answering.', 400)
    now = timezone.now()
    if not attempt.submitted_at:
        if now >= attempt.expires_at:
            # Late payloads cannot change saved answers after either cutoff.
            finish_attempt(attempt, 'timeout', now)
        else:
            d = payload(r)
            if 'answers' in d:
                attempt.answers = validate_answers(exam, d['answers'])
                attempt.save(update_fields=['answers'])
            if r.method == 'POST':
                finish_attempt(attempt, 'manual', now)
    return JsonResponse({'attempt': attempt_json(attempt, r.user), 'server_now': timezone.now()})


@endpoint()
def exam_results(r, pk):
    exam = get_exam(r.user, pk)
    if r.user.id != exam.course.teacher_id:
        raise APIError('Only the class teacher can see class results.', 403)
    finalize_expired([pk])
    members = list(exam.course.memberships.select_related('student').order_by('student__first_name', 'student_id'))
    attempts = {a.student_id: a for a in exam.attempts.select_related('student')}
    rows = []
    for membership in members:
        attempt = attempts.get(membership.student_id)
        rows.append({'student': uj(membership.student), 'status': 'submitted' if attempt and attempt.submitted_at else 'in_progress' if attempt else 'not_started',
                     'attempt': attempt_json(attempt, r.user)})
    completed = [a for a in attempts.values() if a.submitted_at and a.student_id in {m.student_id for m in members}]
    top = sorted(completed, key=lambda a: (-a.score, (a.submitted_at-a.started_at).total_seconds(), a.student_id))[:10]
    question_stats = []
    for q in exam.questions:
        answered = [a.answers.get(q['id']) for a in completed]
        correct = sum(v == q['correct'] for v in answered if v is not None)
        wrong = sum(v != q['correct'] for v in answered if v is not None)
        question_stats.append({'id': q['id'], 'text': q['text'], 'correct': correct, 'wrong': wrong,
                               'unanswered': len(answered)-correct-wrong})
    return JsonResponse({'exam': exam_json(exam, r.user), 'students': rows,
        'summary': {'enrolled': len(members), 'appeared': sum(row['status'] != 'not_started' for row in rows),
            'submitted': len(completed), 'in_progress': sum(row['status'] == 'in_progress' for row in rows),
            'absent': sum(row['status'] == 'not_started' for row in rows),
            'average': round(sum(a.score for a in completed)/len(completed), 2) if completed else 0,
            'highest': max((a.score for a in completed), default=0)},
        'top10': [{'student': uj(a.student), 'score': a.score, 'points': max_score(exam)} for a in top],
        'questions': question_stats, 'server_now': timezone.now()})


@endpoint()
def class_analytics(r, pk):
    c = course(r.user, pk, True)
    finalize_expired(c.exams.values_list('id', flat=True))
    students = []
    for m in c.memberships.select_related('student'):
        attempts = list(ExamAttempt.objects.filter(exam__course=c, student=m.student, submitted_at__isnull=False).select_related('exam'))
        submissions = list(m.student.submission_set.filter(assignment__course=c, grade__isnull=False).select_related('assignment'))
        score = sum(a.score for a in attempts) + sum(s.grade for s in submissions)
        possible = sum(max_score(a.exam) for a in attempts) + sum(s.assignment.points for s in submissions)
        students.append({'student': uj(m.student), 'score': score, 'points': possible,
            'percentage': round(score/possible*100, 1) if possible else None,
            'exams_taken': len(attempts), 'graded_assignments': len(submissions)})
    students.sort(key=lambda s: (-(s['percentage'] if s['percentage'] is not None else -1), -s['score'], s['student']['name']))
    return JsonResponse({'students': students, 'top10': [s for s in students if s['percentage'] is not None][:10],
        'exam_count': c.exams.count(), 'course': c.id})

@endpoint(('POST',))
@transaction.atomic
def open_exam(r, pk):
    exam = get_exam(r.user, pk)
    c = course(r.user, exam.course_id, True)
    now = timezone.now()
    if now >= exam.deadline:
        raise APIError('This exam has already closed.')
    if now < exam.starts_at:
        exam.starts_at, exam.appears_at = now, min(now, exam.appears_at)
        exam.save(update_fields=['starts_at', 'appears_at'])
        Notification.objects.filter(user_id__in=c.memberships.values_list('student_id', flat=True),
            kind='exam', target=f'exam:{exam.id}', available_at__gt=now).delete()
        notify(c, f'Your teacher started the exam: {exam.title}', r.user, kind='exam', target=f'exam:{exam.id}')
    return JsonResponse({'exam': exam_json(exam, r.user), 'server_now': timezone.now()})
