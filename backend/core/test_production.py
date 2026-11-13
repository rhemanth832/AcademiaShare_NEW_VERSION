import io,json,tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase,TransactionTestCase,override_settings
from django.utils import timezone
from .models import User,Course,Membership,Exam,ExamAttempt,ServiceHeartbeat,Notification

class ProductionSecretTests(SimpleTestCase):
    def test_render_generated_secret_is_expanded_stably(self):
        import base64,hashlib
        from academia.security import secret_key
        value=base64.b64encode(bytes(range(32))).decode()
        self.assertEqual(len(value),44)
        self.assertEqual(secret_key(value),hashlib.sha256(bytes(range(32))).hexdigest())
        self.assertEqual(secret_key(value),secret_key(value))
    def test_short_secret_is_rejected(self):
        from academia.security import secret_key
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):secret_key('short-private-key')
    def test_missing_secret_is_rejected(self):
        from academia.security import secret_key
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):secret_key(None)
    def test_repetitive_or_default_secrets_are_rejected(self):
        from academia.security import secret_key
        from django.core.exceptions import ImproperlyConfigured
        for value in ('a'*60,'django-insecure-'+('sample-key-'*6)):
            with self.assertRaises(ImproperlyConfigured):secret_key(value)

class ProductionRuntimeTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.directory=tempfile.TemporaryDirectory()
        self.media=Path(self.directory.name)/'media';self.media.mkdir()
        self.settings=override_settings(MEDIA_ROOT=self.media,SCHEDULER_REQUIRED=True)
        self.settings.enable()
        self.teacher=User.objects.create_user(username='teacher-prod',email='teacher-prod@example.test',role='teacher')
        self.student=User.objects.create_user(username='student-prod',email='student-prod@example.test',role='student')
        self.course=Course.objects.create(name='Production class',code='PROD',teacher=self.teacher)
        Membership.objects.create(course=self.course,student=self.student)
    def tearDown(self):
        self.settings.disable();self.directory.cleanup()
    def test_health_requires_live_worker_and_writable_storage(self):
        self.assertEqual(self.client.get('/api/health/').status_code,503)
        ServiceHeartbeat.objects.create(name='exam-scheduler',updated_at=timezone.now())
        response=self.client.get('/api/health/')
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['database'],'ready')
        self.assertNotIn(str(self.media),response.content.decode())
    def test_stale_scheduler_heartbeat_fails_health(self):
        ServiceHeartbeat.objects.create(name='exam-scheduler',updated_at=timezone.now()-timedelta(seconds=80))
        self.assertEqual(self.client.get('/api/health/').status_code,503)
    def test_missing_storage_fails_readiness(self):
        ServiceHeartbeat.objects.create(name='exam-scheduler')
        with override_settings(MEDIA_ROOT=self.media/'missing'):
            self.assertEqual(self.client.get('/api/health/').status_code,503)
    def test_scheduler_grades_without_any_student_or_teacher_request(self):
        exam=Exam.objects.create(course=self.course,title='Closed browser exam',appears_at=timezone.now()-timedelta(hours=2),starts_at=timezone.now()-timedelta(hours=1),deadline=timezone.now()+timedelta(hours=1),duration_minutes=1,results_mode='immediate',questions=[{'id':'q1','text':'FIFO?','options':['Queue','Stack'],'correct':0,'points':3,'explanation':'Queue is FIFO.'}])
        attempt=ExamAttempt.objects.create(exam=exam,student=self.student,started_at=timezone.now()-timedelta(minutes=2),expires_at=timezone.now()-timedelta(minutes=1),answers={'q1':0})
        call_command('run_exam_scheduler',once=True,stdout=io.StringIO())
        attempt.refresh_from_db()
        self.assertEqual(attempt.completion,'timeout');self.assertEqual(attempt.score,3)
        self.assertTrue(ServiceHeartbeat.objects.filter(name='exam-scheduler').exists())
        self.assertTrue(Notification.objects.filter(user=self.student,kind='result').exists())
    def test_finalizing_an_attempt_twice_does_not_duplicate_notifications(self):
        self.test_scheduler_grades_without_any_student_or_teacher_request()
        before=Notification.objects.count()
        call_command('run_exam_scheduler',once=True,stdout=io.StringIO())
        self.assertEqual(Notification.objects.count(),before)
    def test_login_limits_do_not_merge_unrelated_accounts_behind_one_proxy(self):
        def post(email):return self.client.post('/api/auth/login/',data=json.dumps({'email':email,'password':'wrong','role':'student'}),content_type='application/json')
        with patch('core.views.authenticate',return_value=None):
            for _ in range(30):self.assertEqual(post('one@example.test').status_code,401)
            self.assertEqual(post('one@example.test').status_code,429)
            self.assertEqual(post('two@example.test').status_code,401)
    def test_expired_answer_does_not_overwrite_the_latest_saved_answer(self):
        from .exams import finish_attempt
        e=Exam.objects.create(course=self.course,title='Latest save',appears_at=timezone.now()-timedelta(hours=2),starts_at=timezone.now()-timedelta(hours=1),deadline=timezone.now()+timedelta(hours=1),duration_minutes=1,questions=[{'id':'q1','text':'FIFO?','options':['Queue','Stack'],'correct':0,'points':1}])
        stale=ExamAttempt.objects.create(exam=e,student=self.student,expires_at=timezone.now()-timedelta(seconds=1),answers={})
        ExamAttempt.objects.filter(pk=stale.id).update(answers={'q1':0})
        finish_attempt(stale,'timeout')
        stale.refresh_from_db();self.assertEqual(stale.score,1)

    def test_disk_capacity_is_checked_before_saving_an_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from types import SimpleNamespace
        from .models import Resource
        self.client.force_login(self.teacher)
        with patch('core.views.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            response=self.client.post('/api/files/',{'file':SimpleUploadedFile('notes.txt',b'Class notes',content_type='text/plain'),'course':self.course.id})
        self.assertEqual(response.status_code,507)
        self.assertEqual(Resource.objects.count(),0)
