import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from .models import User, Course, Membership, Exam, ExamAttempt, Notification, VideoCall

class ExamAndCallTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username='teach',email='teach@example.test',role='teacher')
        cls.student = User.objects.create_user(username='student',email='student@example.test',role='student',first_name='Maya')
        cls.other = User.objects.create_user(username='other',email='other@example.test',role='student')
        cls.c = Course.objects.create(name='Algorithms',code='CS301',teacher=cls.teacher)
        Membership.objects.create(course=cls.c,student=cls.student)
    def setUp(self):
        self.now=timezone.now()
        self.client.force_login(self.teacher)
        self.spec={'title':'Trees exam','course':self.c.id,'description':'Pick one answer.',
            'appears_at':(self.now-timedelta(minutes=5)).isoformat(),'starts_at':(self.now-timedelta(minutes=1)).isoformat(),
            'deadline':(self.now+timedelta(hours=2)).isoformat(),'duration_minutes':60,'results_mode':'after_deadline',
            'questions':[{'text':'What is FIFO?','options':['Queue','Stack','Tree'],'correct':0,'points':2,'explanation':'Queues are FIFO.'},
                         {'text':'Which uses LIFO?','options':['Queue','Stack'],'correct':1,'points':3}]}
    def req(self,path,d=None,method='POST'):
        return getattr(self.client,method.lower())('/api/'+path,data=json.dumps(d or {}),content_type='application/json')
    def create(self,**updates):
        r=self.req('exams/',{**self.spec,**updates});self.assertEqual(r.status_code,201,r.content)
        return Exam.objects.get(pk=r.json()['id'])
    def start(self,exam):
        self.client.force_login(self.student);r=self.req(f'exams/{exam.id}/start/');self.assertEqual(r.status_code,200,r.content)
        return ExamAttempt.objects.get(pk=r.json()['attempt']['id'])
    def test_students_and_unrelated_teachers_cannot_create_exams(self):
        self.client.force_login(self.student);self.assertEqual(self.req('exams/',self.spec).status_code,403)
        t=User.objects.create_user(username='outsider',email='outsider@example.test',role='teacher')
        self.client.force_login(t);self.assertEqual(self.req('exams/',self.spec).status_code,404)
    def test_validate_questions_schedule_and_duration(self):
        for changes in [{'duration_minutes':0},{'duration_minutes':True},{'duration_minutes':481},
                        {'starts_at':self.spec['deadline']},{'appears_at':self.spec['deadline']},
                        {'questions':[]},{'results_mode':'foo'},
                        {'questions':[{'text':'Q','options':['same','same'],'correct':0}]},
                        {'questions':[{'text':'Q','options':['a','b'],'correct':2}]}]:
            self.assertEqual(self.req('exams/',{**self.spec,**changes}).status_code,400,changes)
        self.assertEqual(Exam.objects.count(),0)
    def test_appearance_hides_exam_notifications_and_activity(self):
        e=self.create(appears_at=(self.now+timedelta(minutes=10)).isoformat(),starts_at=(self.now+timedelta(minutes=20)).isoformat())
        self.client.force_login(self.student);state=self.client.get('/api/state/').json()
        self.assertEqual(state['exams'],[]);self.assertEqual(state['notifications'],[])
        self.assertFalse(any(e.title in a['text'] for a in state['activity']))
        self.assertEqual(self.client.get(f'/api/exams/{e.id}/').status_code,404)
        self.req('notifications/read/')
        self.assertFalse(Notification.objects.filter(user=self.student,read=True).exists())
    def test_start_gate_cutoff_and_authorization(self):
        e=self.create(starts_at=(self.now+timedelta(minutes=10)).isoformat())
        self.client.force_login(self.student);self.assertEqual(self.req(f'exams/{e.id}/start/').status_code,400)
        self.client.force_login(self.other);self.assertEqual(self.req(f'exams/{e.id}/start/').status_code,404)
        self.assertEqual(self.client.get(f'/api/exams/{e.id}/results/').status_code,404)
        self.client.force_login(self.teacher);self.assertEqual(self.req(f'exams/{e.id}/start/').status_code,403)
    def test_single_attempt_resume_and_deadline_clamps_timer(self):
        e=self.create(deadline=(self.now+timedelta(minutes=10)).isoformat())
        a=self.start(e);r=self.req(f'exams/{e.id}/start/');self.assertEqual(a.id,r.json()['attempt']['id'])
        self.assertEqual(a.expires_at,e.deadline);self.assertEqual(ExamAttempt.objects.count(),1)
        self.client.force_login(self.teacher);self.assertEqual(self.client.get(f'/api/exams/{e.id}/results/').json()['summary']['appeared'],1)
    def test_no_question_or_key_leak_and_private_class_results(self):
        e=self.create();self.client.force_login(self.student)
        before=self.client.get(f'/api/exams/{e.id}/').json()['exam'];self.assertNotIn('questions',before)
        self.start(e);detail=self.client.get(f'/api/exams/{e.id}/').json()['exam']
        self.assertNotIn('correct',detail['questions'][0]);self.assertNotIn('explanation',detail['questions'][0])
        self.assertEqual(self.client.get(f'/api/exams/{e.id}/results/').status_code,403)
        self.assertEqual(self.client.get(f'/api/courses/{self.c.id}/analytics/').status_code,404)
    def test_grading_ignores_forged_scores_and_delays_solutions(self):
        e=self.create();a=self.start(e);q=e.questions
        r=self.req(f'exams/{e.id}/answers/',{'answers':{q[0]['id']:0,q[1]['id']:0},'score':999,'correct':99})
        self.assertEqual(r.status_code,200);self.assertNotIn('score',r.json()['attempt']);self.assertNotIn('review',r.json()['attempt'])
        a.refresh_from_db();self.assertEqual((a.score,a.correct,a.wrong),(2,1,1))
        self.client.force_login(self.teacher);result=self.client.get(f'/api/exams/{e.id}/results/').json()
        self.assertEqual(result['students'][0]['attempt']['score'],2)
        self.assertEqual(result['questions'][1]['wrong'],1)
        self.client.force_login(self.student)
        with patch('core.exams.timezone.now',return_value=e.deadline+timedelta(seconds=1)):
            released=self.client.get(f'/api/exams/{e.id}/').json()['exam']['my_attempt']
        self.assertEqual(released['review'][0]['correct'],0)
    def test_immediate_results_correct_wrong_and_unanswered(self):
        e=self.create(results_mode='immediate');a=self.start(e)
        r=self.req(f'exams/{e.id}/answers/',{'answers':{e.questions[1]['id']:1}}).json()['attempt']
        self.assertEqual((r['score'],r['correct'],r['wrong'],r['unanswered']),(3,1,0,1))
        self.assertTrue(r['results_available'])
    def test_auto_timeout_uses_saved_answers_and_rejects_late_changes(self):
        e=self.create(results_mode='immediate');a=self.start(e);qid=e.questions[0]['id']
        self.req(f'exams/{e.id}/answers/',{'answers':{qid:0}},method='PATCH')
        ExamAttempt.objects.filter(pk=a.id).update(expires_at=self.now-timedelta(seconds=1))
        r=self.req(f'exams/{e.id}/answers/',{'answers':{qid:1,e.questions[1]['id']:1}}).json()['attempt']
        self.assertEqual(r['completion'],'timeout');self.assertEqual(r['score'],2);self.assertEqual(r['answers'],{qid:0})
        self.assertEqual(self.req(f'exams/{e.id}/start/').json()['attempt']['id'],a.id)
    def test_closed_browser_is_finalized_when_teacher_reads_state(self):
        e=self.create();a=self.start(e);ExamAttempt.objects.filter(pk=a.id).update(expires_at=self.now-timedelta(seconds=1))
        self.client.force_login(self.teacher);self.client.get('/api/state/');a.refresh_from_db()
        self.assertIsNotNone(a.submitted_at);self.assertEqual(a.completion,'timeout');self.assertEqual(a.unanswered,2)
    def test_answer_validation_and_submission_idempotency(self):
        e=self.create();a=self.start(e);qid=e.questions[0]['id']
        for answers in [{qid:True},{qid:20},{'not-a-question':0},[]]:
            self.assertEqual(self.req(f'exams/{e.id}/answers/',{'answers':answers},method='PATCH').status_code,400)
        self.req(f'exams/{e.id}/answers/',{'answers':{qid:0}})
        self.req(f'exams/{e.id}/answers/',{'answers':{qid:1}})
        a.refresh_from_db();self.assertEqual(a.score,2)
        self.assertEqual(Notification.objects.filter(user=self.student,kind='result').count(),1)
    def test_roster_absentees_rankings_and_class_analytics(self):
        for i in range(12):
            student=User.objects.create_user(username=f'learner{i}',email=f'learner{i}@example.test',role='student',first_name=f'Learner {i}')
            Membership.objects.create(course=self.c,student=student)
        e=self.create();self.start(e);self.req(f'exams/{e.id}/answers/',{'answers':{q['id']:q['correct'] for q in e.questions}})
        self.client.force_login(self.teacher);r=self.client.get(f'/api/exams/{e.id}/results/').json()
        self.assertEqual(r['summary']['enrolled'],13);self.assertEqual(r['summary']['absent'],12)
        self.assertEqual(r['top10'][0]['score'],5)
        r=self.client.get(f'/api/courses/{self.c.id}/analytics/').json()
        self.assertEqual(len(r['students']),13);self.assertEqual(r['top10'][0]['percentage'],100)
        self.assertIsNone(r['students'][-1]['percentage'])
    def test_notification_categories_reach_only_enrolled_students(self):
        self.req('announcements/',{'course':self.c.id,'title':'Notice','body':'Read this'})
        self.req('assignments/',{'course':self.c.id,'title':'Task','description':'Upload work','due':self.spec['deadline'],'points':10})
        self.create()
        self.client.force_login(self.student);n=self.client.get('/api/state/').json()['notifications']
        self.assertTrue({'announcement','assignment','exam'} <= {v['kind'] for v in n})
        self.client.force_login(self.other);self.assertEqual(self.client.get('/api/state/').json()['notifications'],[])
    def make_call(self,**changes):
        data={'course':self.c.id,'title':'Live lesson','description':'Practice','starts_at':self.now.isoformat(),**changes}
        r=self.req('calls/',data);self.assertEqual(r.status_code,201,r.content);return r.json()['id']
    def test_calls_schedule_start_join_end_and_membership(self):
        call=self.make_call();self.client.force_login(self.student)
        self.assertEqual(self.req(f'calls/{call}/join/').status_code,400)
        self.assertEqual(self.req(f'calls/{call}/start/').status_code,404)
        self.client.force_login(self.teacher);self.assertEqual(self.req(f'calls/{call}/start/').status_code,200)
        self.client.force_login(self.student);url=self.req(f'calls/{call}/join/').json()['join_url']
        self.assertTrue(url.startswith('https://meet.jit.si/AcademiaShare-'))
        self.client.force_login(self.other);self.assertEqual(self.req(f'calls/{call}/join/').status_code,404)
        self.client.force_login(self.teacher);self.assertEqual(self.req(f'calls/{call}/end/').status_code,200)
        self.client.force_login(self.student);self.assertEqual(self.req(f'calls/{call}/join/').status_code,400)
    def test_call_link_validation_live_creation_and_notifications(self):
        self.assertEqual(self.req('calls/',{'course':self.c.id,'title':'Bad','starts_at':self.now.isoformat(),'join_url':'javascript:alert(1)'}).status_code,400)
        call=self.make_call(start_now=True,join_url='https://meet.google.com/abc-defg-hij')
        self.client.force_login(self.student)
        self.assertEqual(self.req(f'calls/{call}/join/').json()['join_url'],'https://meet.google.com/abc-defg-hij')
        self.assertTrue(Notification.objects.filter(user=self.student,kind='call').exists())
        self.assertFalse(Notification.objects.filter(user=self.other).exists())
    def test_teacher_can_open_early_without_extending_deadline(self):
        e=self.create(appears_at=(self.now+timedelta(minutes=5)).isoformat(),starts_at=(self.now+timedelta(minutes=10)).isoformat())
        old=e.deadline
        self.client.force_login(self.student);self.assertEqual(self.req(f'exams/{e.id}/open/').status_code,404)
        self.client.force_login(self.teacher);self.assertEqual(self.req(f'exams/{e.id}/open/').status_code,200)
        e.refresh_from_db();self.assertLessEqual(e.starts_at,timezone.now());self.assertEqual(e.deadline,old)
        self.client.force_login(self.student);self.assertEqual(len(self.client.get('/api/state/').json()['exams']),1)
        self.assertEqual(self.req(f'exams/{e.id}/start/').status_code,200)
    def test_top10_is_capped_and_sorted_and_excludes_absentees(self):
        e=self.create();q=e.questions
        for i in range(12):
            u=User.objects.create_user(username=f'ranked{i}',email=f'ranked{i}@example.test',role='student',first_name=f'Ranked {i}')
            Membership.objects.create(course=self.c,student=u)
            ExamAttempt.objects.create(exam=e,student=u,started_at=self.now,expires_at=self.now+timedelta(hours=1),submitted_at=self.now+timedelta(minutes=5),score=i%6,correct=0,wrong=2,unanswered=0)
        result=self.client.get(f'/api/exams/{e.id}/results/').json()
        self.assertEqual(len(result['top10']),10)
        self.assertEqual([v['score'] for v in result['top10']],sorted([v['score'] for v in result['top10']],reverse=True))
        self.assertEqual(result['summary']['absent'],1)
    def test_not_started_student_cannot_start_at_deadline(self):
        e=self.create();self.client.force_login(self.student)
        with patch('core.exams.timezone.now',return_value=e.deadline):
            self.assertEqual(self.req(f'exams/{e.id}/start/').status_code,400)
        self.assertEqual(ExamAttempt.objects.count(),0)
    def test_single_notification_read_is_scoped_to_user_and_schedule(self):
        n=Notification.objects.create(user=self.student,text='Mine')
        other=Notification.objects.create(user=self.other,text='Private')
        future=Notification.objects.create(user=self.student,text='Future',available_at=self.now+timedelta(hours=2))
        self.client.force_login(self.student)
        self.req('notifications/read/',{'id':other.id});other.refresh_from_db();self.assertFalse(other.read)
        self.req('notifications/read/',{'id':future.id});future.refresh_from_db();self.assertFalse(future.read)
        self.req('notifications/read/',{'id':n.id});n.refresh_from_db();self.assertTrue(n.read)
