import secrets,uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
def invite_code(): return secrets.token_hex(4).upper()
def upload_path(instance,filename): return f'uploads/{uuid.uuid4().hex}.{filename.rsplit(".",1)[-1].lower()}'
class User(AbstractUser):
    email=models.EmailField(unique=True)
    role=models.CharField(max_length=10,choices=[('teacher','Teacher'),('student','Student')])
    department=models.CharField(max_length=120,blank=True)
    institution=models.CharField(max_length=150,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(Lower('email'),name='unique_email_case_insensitive')]
class Course(models.Model):
    name=models.CharField(max_length=120)
    code=models.CharField(max_length=24)
    description=models.TextField(blank=True)
    teacher=models.ForeignKey(User,on_delete=models.CASCADE,related_name='teaching')
    color=models.CharField(max_length=20,default='peach')
    invite_code=models.CharField(max_length=16,unique=True,default=invite_code)
    created_at=models.DateTimeField(auto_now_add=True)
class Membership(models.Model):
    course=models.ForeignKey(Course,on_delete=models.CASCADE,related_name='memberships')
    student=models.ForeignKey(User,on_delete=models.CASCADE,related_name='enrollments')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['course','student'],name='unique_membership')]
class Folder(models.Model):
    name=models.CharField(max_length=120)
    owner=models.ForeignKey(User,on_delete=models.CASCADE)
    course=models.ForeignKey(Course,null=True,blank=True,on_delete=models.CASCADE)
    parent=models.ForeignKey('self',null=True,blank=True,on_delete=models.CASCADE,related_name='children')
    color=models.CharField(max_length=20,default='peach')
    deleted_at=models.DateTimeField(null=True,blank=True)
    trash_batch=models.CharField(max_length=36,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
class Resource(models.Model):
    name=models.CharField(max_length=180)
    owner=models.ForeignKey(User,on_delete=models.CASCADE)
    course=models.ForeignKey(Course,null=True,blank=True,on_delete=models.CASCADE)
    folder=models.ForeignKey(Folder,null=True,blank=True,on_delete=models.CASCADE,related_name='resources')
    file=models.FileField(upload_to=upload_path)
    size=models.PositiveBigIntegerField(default=0)
    mime=models.CharField(max_length=120,default='application/octet-stream')
    description=models.TextField(blank=True)
    starred_by=models.ManyToManyField(User,related_name='starred_resources',blank=True)
    deleted_at=models.DateTimeField(null=True,blank=True)
    trash_batch=models.CharField(max_length=36,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
class Assignment(models.Model):
    title=models.CharField(max_length=180)
    description=models.TextField()
    course=models.ForeignKey(Course,on_delete=models.CASCADE,related_name='assignments')
    due=models.DateTimeField()
    points=models.PositiveIntegerField(default=100)
    allow_late=models.BooleanField(default=True)
    created_at=models.DateTimeField(auto_now_add=True)
class Submission(models.Model):
    assignment=models.ForeignKey(Assignment,on_delete=models.CASCADE,related_name='submissions')
    student=models.ForeignKey(User,on_delete=models.CASCADE)
    file=models.FileField(upload_to=upload_path)
    name=models.CharField(max_length=180)
    size=models.PositiveBigIntegerField(default=0)
    note=models.TextField(blank=True)
    grade=models.PositiveIntegerField(null=True,blank=True)
    feedback=models.TextField(blank=True)
    submitted_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['assignment','student'],name='unique_submission')]
class Announcement(models.Model):
    title=models.CharField(max_length=180)
    body=models.TextField()
    course=models.ForeignKey(Course,on_delete=models.CASCADE)
    author=models.ForeignKey(User,on_delete=models.CASCADE)
    created_at=models.DateTimeField(auto_now_add=True)
class Notification(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE)
    text=models.CharField(max_length=255)
    read=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    available_at=models.DateTimeField(default=timezone.now,db_index=True)
    kind=models.CharField(max_length=24,default='general')
    target=models.CharField(max_length=100,blank=True)
class Activity(models.Model):
    actor=models.ForeignKey(User,on_delete=models.CASCADE)
    course=models.ForeignKey(Course,null=True,blank=True,on_delete=models.CASCADE)
    text=models.CharField(max_length=255)
    created_at=models.DateTimeField(auto_now_add=True)

class Exam(models.Model):
    course=models.ForeignKey(Course,on_delete=models.CASCADE,related_name='exams')
    title=models.CharField(max_length=180)
    description=models.TextField(blank=True)
    appears_at=models.DateTimeField()
    starts_at=models.DateTimeField()
    deadline=models.DateTimeField()
    duration_minutes=models.PositiveIntegerField(default=60)
    results_mode=models.CharField(max_length=24,default='after_deadline',choices=[('after_deadline','After deadline'),('immediate','After submission')])
    questions=models.JSONField(default=list)
    created_at=models.DateTimeField(auto_now_add=True)

class ExamAttempt(models.Model):
    exam=models.ForeignKey(Exam,on_delete=models.CASCADE,related_name='attempts')
    student=models.ForeignKey(User,on_delete=models.CASCADE,related_name='exam_attempts')
    started_at=models.DateTimeField(default=timezone.now)
    expires_at=models.DateTimeField()
    answers=models.JSONField(default=dict)
    submitted_at=models.DateTimeField(null=True,blank=True)
    completion=models.CharField(max_length=12,blank=True)
    score=models.PositiveIntegerField(default=0)
    correct=models.PositiveIntegerField(default=0)
    wrong=models.PositiveIntegerField(default=0)
    unanswered=models.PositiveIntegerField(default=0)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['exam','student'],name='one_exam_attempt_per_student')]

class VideoCall(models.Model):
    course=models.ForeignKey(Course,on_delete=models.CASCADE,related_name='video_calls')
    title=models.CharField(max_length=180)
    description=models.TextField(blank=True)
    starts_at=models.DateTimeField()
    status=models.CharField(max_length=12,default='scheduled',choices=[('scheduled','Scheduled'),('live','Live'),('ended','Ended')])
    join_url=models.URLField(max_length=1000)
    started_at=models.DateTimeField(null=True,blank=True)
    ended_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

class ServiceHeartbeat(models.Model):
    name=models.CharField(max_length=60,primary_key=True)
    updated_at=models.DateTimeField(default=timezone.now)
