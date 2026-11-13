import json,tempfile,shutil
from datetime import timedelta
from django.test import TestCase,Client,override_settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from .models import User,Course,Membership,Folder,Resource,Assignment,Submission

class SharingTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.media=tempfile.mkdtemp();cls.override=override_settings(MEDIA_ROOT=cls.media);cls.override.enable()
    @classmethod
    def tearDownClass(cls):
        cls.override.disable();shutil.rmtree(cls.media,ignore_errors=True);super().tearDownClass()
    def setUp(self):
        cache.clear()
        self.teacher=User.objects.create_user(username='alex@example.test',email='alex@example.test',password='Example!Password24',role='teacher',first_name='Alex')
        self.student=User.objects.create_user(username='maya@example.test',email='maya@example.test',password='Example!Password24',role='student',first_name='Maya')
        self.other=User.objects.create_user(username='other@example.test',email='other@example.test',password='Example!Password24',role='teacher',first_name='Other')
        self.course=Course.objects.create(name='Algorithms',code='CS301',teacher=self.teacher)
        self.folder=Folder.objects.create(name='Notes',owner=self.teacher,course=self.course)
        self.client.force_login(self.teacher)
    def post(self,path,data):return self.client.post('/api/'+path,data=json.dumps(data),content_type='application/json')
    def patch(self,path,data):return self.client.patch('/api/'+path,data=json.dumps(data),content_type='application/json')
    def file(self,name='lesson.pdf',content=b'%PDF-1.4 lesson'):
        return SimpleUploadedFile(name,content,content_type='application/pdf')
    def upload(self,**fields):return self.client.post('/api/files/',{'file':self.file(),**fields})
    def enroll(self):Membership.objects.create(course=self.course,student=self.student)
    def test_anonymous_cannot_read_state_or_upload(self):
        self.client.logout();self.assertEqual(self.client.get('/api/state/').status_code,401);self.assertEqual(self.upload().status_code,401)
    def test_distinct_login_roles_and_registration(self):
        self.client.logout();wrong=self.post('auth/login/',{'email':self.student.email,'password':'Example!Password24','role':'teacher'});self.assertEqual(wrong.status_code,401)
        response=self.post('auth/register/',{'name':'New Learner','email':'NEW@example.test','password':'Learner!Pass2026','role':'student'})
        self.assertEqual(response.status_code,201);self.assertEqual(response.json()['user']['role'],'student');self.assertEqual(User.objects.get(email='new@example.test').username,'new@example.test')
        self.client.logout();self.assertEqual(self.post('auth/register/',{'name':'Duplicate','email':'new@EXAMPLE.test','password':'Learner!Pass2026','role':'teacher'}).status_code,409)
    def test_csrf_required_and_login_rotation(self):
        c=Client(enforce_csrf_checks=True)
        self.assertEqual(c.post('/api/auth/login/',data=json.dumps({'email':self.teacher.email,'password':'Example!Password24','role':'teacher'}),content_type='application/json').status_code,403)
        token=c.get('/api/auth/csrf/').json()['csrfToken']
        r=c.post('/api/auth/login/',data=json.dumps({'email':self.teacher.email,'password':'Example!Password24','role':'teacher'}),content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code,200);self.assertEqual(c.get('/api/state/').status_code,200)
    def test_invite_join_is_idempotent_and_private(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(f'/api/courses/{self.course.id}/').status_code,404)
        for _ in range(2):self.assertEqual(self.post('courses/join/',{'code':self.course.invite_code.lower()}).status_code,200)
        self.assertEqual(Membership.objects.count(),1);r=self.client.get(f'/api/courses/{self.course.id}/').json();self.assertEqual(r['members'],[]);self.assertEqual(r['course']['invite_code'],'')
    def test_students_cannot_create_classes_or_class_folders(self):
        self.enroll();self.client.force_login(self.student)
        self.assertEqual(self.post('courses/',{'name':'Bad','code':'BAD'}).status_code,403)
        self.assertEqual(self.post('folders/',{'name':'Bad','course':self.course.id}).status_code,404)
        self.assertEqual(self.post('folders/',{'name':'My notes'}).status_code,201)
    def test_class_files_require_membership_and_private_files_stay_private(self):
        shared=self.upload(course=self.course.id,folder=self.folder.id).json()['id'];private=self.upload().json()['id']
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(f'/api/files/{shared}/download/').status_code,404)
        self.enroll();self.assertEqual(self.client.get(f'/api/files/{shared}/download/').status_code,200)
        self.assertEqual(self.client.get(f'/api/files/{private}/download/').status_code,404)
        visible={f['id'] for f in self.client.get('/api/state/').json()['files']};self.assertIn(shared,visible);self.assertNotIn(private,visible)
        self.assertEqual(self.patch(f'files/{shared}/',{'name':'renamed.pdf'}).status_code,403)
    def test_unrelated_teacher_cannot_read_or_mutate(self):
        f=self.upload(course=self.course.id).json()['id'];self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/api/files/{f}/download/').status_code,404)
        self.assertEqual(self.patch(f'files/{f}/',{'folder':None}).status_code,403)
        self.assertEqual(self.post('assignments/',{'course':self.course.id,'title':'No access'}).status_code,404)
    def test_nested_folders_cannot_form_cycles_or_cross_classes(self):
        sub=self.post('folders/',{'name':'Unit 1','parent':self.folder.id,'course':self.course.id}).json()['id']
        self.assertEqual(self.patch(f'folders/{self.folder.id}/',{'parent':sub}).status_code,400)
        other=Course.objects.create(name='Networks',code='CN',teacher=self.teacher);p=Folder.objects.create(name='Other class',course=other,owner=self.teacher)
        self.assertEqual(self.patch(f'folders/{sub}/',{'parent':p.id}).status_code,400)
        self.assertEqual(self.post('folders/',{'name':'notes','course':self.course.id}).status_code,400)
    def test_folder_trash_restore_preserves_separately_trashed_file(self):
        sub=self.post('folders/',{'name':'Subfolder','parent':self.folder.id,'course':self.course.id}).json()['id']
        first=self.upload(folder=sub,course=self.course.id).json()['id'];second=self.upload(folder=sub,course=self.course.id).json()['id']
        self.client.delete(f'/api/files/{first}/');self.client.delete(f'/api/folders/{self.folder.id}/')
        self.assertTrue(Resource.objects.get(id=second).deleted_at);self.assertTrue(Folder.objects.get(id=sub).deleted_at)
        self.patch(f'folders/{self.folder.id}/',{'restore':True})
        self.assertIsNone(Resource.objects.get(id=second).deleted_at);self.assertIsNotNone(Resource.objects.get(id=first).deleted_at)
    def test_move_shared_file_to_private_revokes_access(self):
        f=self.upload(course=self.course.id,folder=self.folder.id).json()['id'];self.enroll()
        self.assertEqual(self.patch(f'files/{f}/',{'course':None,'folder':None}).status_code,200)
        self.client.force_login(self.student);self.assertEqual(self.client.get(f'/api/files/{f}/download/').status_code,404)
    def test_star_is_per_user_and_download_is_attachment(self):
        f=self.upload(course=self.course.id).json()['id'];self.enroll();self.post(f'files/{f}/star/',{})
        response=self.client.get(f'/api/files/{f}/download/');self.assertIn('attachment',response['Content-Disposition']);self.assertEqual(response['Cache-Control'],'private, no-store')
        self.client.force_login(self.student);self.assertFalse(self.client.get('/api/state/').json()['files'][0]['starred'])
    def test_upload_validation_and_storage_quota(self):
        self.assertEqual(self.client.post('/api/files/',{'file':self.file('attack.html',b'<script>bad</script>')}).status_code,400)
        with override_settings(MAX_RESOURCE_SIZE=4):self.assertEqual(self.upload().status_code,400)
        with override_settings(USER_STORAGE_LIMIT=20):
            self.assertEqual(self.upload().status_code,201);self.assertEqual(self.upload().status_code,400)
    def test_assignment_submission_grading_feedback_and_isolation(self):
        self.enroll();a=self.post('assignments/',{'title':'Implement a tree','description':'Upload your work','course':self.course.id,'due':(timezone.now()+timedelta(days=2)).isoformat(),'points':50,'allow_late':True}).json()['id']
        self.client.force_login(self.student);s=self.client.post(f'/api/assignments/{a}/submissions/',{'file':self.file(),'note':'My work'});self.assertEqual(s.status_code,201);sid=s.json()['id']
        self.assertEqual(self.patch(f'submissions/{sid}/',{'grade':50}).status_code,404)
        self.client.force_login(self.other);self.assertEqual(self.client.get(f'/api/submissions/{sid}/download/').status_code,404)
        self.client.force_login(self.teacher);self.assertEqual(self.patch(f'submissions/{sid}/',{'grade':51}).status_code,400);self.assertEqual(self.patch(f'submissions/{sid}/',{'grade':48,'feedback':'Great work!'}).status_code,200)
        self.client.force_login(self.student);mine=self.client.get('/api/state/').json()['assignments'][0]['my_submission'];self.assertEqual(mine['grade'],48);self.assertEqual(mine['feedback'],'Great work!');self.assertEqual(self.client.post(f'/api/assignments/{a}/submissions/',{'file':self.file()}).status_code,400)
    def test_late_submission_rules(self):
        self.enroll();a=Assignment.objects.create(title='Closed',description='Past due',course=self.course,due=timezone.now()-timedelta(hours=1),allow_late=False)
        self.client.force_login(self.student);self.assertEqual(self.client.post(f'/api/assignments/{a.id}/submissions/',{'file':self.file()}).status_code,400)
    def test_teacher_announcement_reaches_only_class(self):
        self.enroll();self.assertEqual(self.post('announcements/',{'title':'Hello','body':'Class update','course':self.course.id}).status_code,201)
        self.client.force_login(self.student);self.assertEqual(len(self.client.get('/api/state/').json()['announcements']),1);self.assertEqual(self.post('announcements/',{'course':self.course.id,'title':'Bad','body':'No'}).status_code,403)
        self.client.force_login(self.other);self.assertEqual(self.client.get('/api/state/').json()['announcements'],[])
    def test_empty_trash_removes_only_owned_trashed_files(self):
        active=self.upload().json()['id'];trash=self.upload().json()['id'];self.client.delete(f'/api/files/{trash}/')
        self.assertEqual(self.post('trash/empty/',{}).status_code,200);self.assertTrue(Resource.objects.filter(id=active).exists());self.assertFalse(Resource.objects.filter(id=trash).exists())
