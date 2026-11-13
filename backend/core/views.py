import json,mimetypes,uuid,os,hashlib,shutil
from functools import wraps
from pathlib import Path
from django.conf import settings
from django.contrib.auth import authenticate,login,logout,update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError,transaction
from django.db.models import Q,Sum
from django.http import JsonResponse,FileResponse,HttpResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import User,Course,Membership,Folder,Resource,Assignment,Submission,Announcement,Notification,Activity

class APIError(Exception):
    def __init__(self,message,status=400): self.message,self.status=message,status
def endpoint(methods=('GET',),public=False):
    def decorate(fn):
        @wraps(fn)
        def wrapped(r,*args,**kwargs):
            if r.method not in methods:return JsonResponse({'error':'Method not allowed.'},status=405)
            if not public and not r.user.is_authenticated:return JsonResponse({'error':'Please sign in to continue.'},status=401)
            try:
                response=fn(r,*args,**kwargs)
                if 'Cache-Control' not in response:response['Cache-Control']='private, no-store'
                return response
            except APIError as e:return JsonResponse({'error':e.message},status=e.status)
            except ValidationError as e:return JsonResponse({'error':' '.join(e.messages)},status=400)
            except (ValueError,TypeError,AttributeError):return JsonResponse({'error':'Check the submitted values and try again.'},status=400)
            except IntegrityError:return JsonResponse({'error':'This item already exists. Choose a different value.'},status=409)
        return wrapped
    return decorate
def payload(r):
    d=json.loads(r.body or '{}')
    if not isinstance(d,dict):raise APIError('A JSON object is required.')
    return d
def text(d,key,limit=180,required=True):
    value=d.get(key,'')
    if not isinstance(value,str):raise APIError(f'{key} must be text.')
    value=value.strip()
    if required and not value:raise APIError(f'{key.replace("_"," ").capitalize()} is required.')
    if len(value)>limit:raise APIError(f'{key.capitalize()} must be {limit} characters or fewer.')
    return value
def uj(u):return {'id':u.id,'name':u.first_name or u.username.split('@')[0],'email':u.email,'role':u.role,'department':u.department,'institution':u.institution}
def ids(u):return Course.objects.filter(Q(teacher=u)|Q(memberships__student=u)).distinct().values_list('id',flat=True)
def teacher(u):
    if u.role!='teacher':raise APIError('Only teachers can perform this action.',403)
def course(u,pk,write=False):
    c=Course.objects.filter(pk=pk).first()
    if not c or (write and c.teacher_id!=u.id) or (not write and c.id not in ids(u)):raise APIError('Class not found or access denied.',404)
    return c
def folder(u,pk,write=False):
    if not pk:return None
    f=Folder.objects.filter(pk=pk).first()
    if not f or (write and f.owner_id!=u.id) or (not write and f.owner_id!=u.id and (not f.course_id or f.course_id not in ids(u))):raise APIError('Folder not found or access denied.',404)
    if f.deleted_at:raise APIError('Restore this folder from the trash first.')
    return f
def resource(u,pk,write=False,trash=False):
    f=Resource.objects.select_related('owner','folder','course').filter(pk=pk).first()
    if not f or (f.deleted_at and not trash):raise APIError('File not found.',404)
    if write and f.owner_id!=u.id:raise APIError('You can only change your own resources.',403)
    if not write and f.owner_id!=u.id and (not f.course_id or f.course_id not in ids(u)):raise APIError('File not found.',404)
    if f.deleted_at and f.owner_id!=u.id:raise APIError('File not found.',404)
    return f
def cj(c,u):return {'id':c.id,'name':c.name,'code':c.code,'description':c.description,'teacher':uj(c.teacher),'color':c.color,'invite_code':c.invite_code if c.teacher_id==u.id else '','students':c.memberships.count(),'member_preview':list(c.memberships.select_related('student').values_list('student__first_name',flat=True)[:3]),'created_at':c.created_at}
def fj(f):return {'id':f.id,'name':f.name,'owner':f.owner_id,'course':f.course_id,'parent':f.parent_id,'color':f.color,'deleted_at':f.deleted_at,'created_at':f.created_at}
def rj(f,u):return {'id':f.id,'name':f.name,'owner':uj(f.owner),'course':f.course_id,'folder':f.folder_id,'size':f.size,'mime':f.mime,'description':f.description,'starred':f.starred_by.filter(id=u.id).exists(),'deleted_at':f.deleted_at,'created_at':f.created_at,'updated_at':f.updated_at,'download_url':f'/api/files/{f.id}/download/'}
def sj(s):return {'id':s.id,'student':uj(s.student),'name':s.name,'size':s.size,'note':s.note,'grade':s.grade,'feedback':s.feedback,'submitted_at':s.submitted_at,'download_url':f'/api/submissions/{s.id}/download/'}
def aj(a,u):
    s=a.submissions.filter(student=u).first()
    return {'id':a.id,'title':a.title,'description':a.description,'course':a.course_id,'due':a.due,'points':a.points,'allow_late':a.allow_late,'submission_count':a.submissions.count(),'my_submission':sj(s) if s else None,'created_at':a.created_at}
def activity(u,message,c=None):Activity.objects.create(actor=u,text=message[:255],course=c)
def notify(c,message,u,kind="general",target="",available_at=None):
    users=set(c.memberships.exclude(student=u).values_list('student_id',flat=True))
    if c.teacher_id!=u.id:users.add(c.teacher_id)
    Notification.objects.bulk_create([Notification(user_id=i,text=message[:255],kind=kind,target=target,available_at=available_at or timezone.now()) for i in users])
def storage(u):return (Resource.objects.filter(owner=u).aggregate(s=Sum('size'))['s'] or 0)+(Submission.objects.filter(student=u).aggregate(s=Sum('size'))['s'] or 0)
def upload(r,replacing_size=0):
    f=r.FILES.get('file')
    if not f or not f.size or f.size>settings.MAX_RESOURCE_SIZE:raise APIError('Choose a file between 1 byte and 25 MB.')
    if storage(r.user)-replacing_size+f.size>settings.USER_STORAGE_LIMIT:raise APIError('Your 500 MB storage is full. Empty the trash to free space.')
    if Path(f.name).suffix.lower() not in {'.pdf','.doc','.docx','.ppt','.pptx','.xls','.xlsx','.txt','.csv','.md','.png','.jpg','.jpeg','.gif','.webp','.zip','.mp4','.mp3'}:raise APIError('Use a document, PDF, image, ZIP, MP3, or MP4 file.')
    media_root=Path(settings.MEDIA_ROOT);media_root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(media_root).free < f.size+10*1024*1024:raise APIError('Workspace storage is full. Ask your administrator to free space or expand storage.',507)
    return f
def throttle(r,kind,limit=30,identity=''):
    # Account-specific limits avoid grouping an entire campus behind one NAT/proxy.
    # Independent IP-wide registration limits still deter account-creation floods.
    raw=f'{kind}:{identity.lower()}' if identity else f'{kind}:{r.META.get("REMOTE_ADDR","unknown")}'
    key='academia-throttle:'+hashlib.sha256(raw.encode()).hexdigest()
    n=cache.get(key,0)
    if n>=limit:raise APIError('Too many attempts. Please wait 10 minutes.',429)
    cache.set(key,n+1,600)
def color(d):return d.get('color') if d.get('color') in ('peach','mint','lavender','blue') else 'peach'
def subtree(f):
    result,level=[f.id],[f.id]
    while level:
        level=list(Folder.objects.filter(parent_id__in=level).values_list('id',flat=True));result.extend(level)
    return result

@endpoint(public=True)
def csrf(r):return JsonResponse({'csrfToken':get_token(r)})
@endpoint(('POST',),public=True)
def register(r):
    d=payload(r)
    if d.get('role') not in ('teacher','student'):raise APIError('Choose a teacher or student account.')
    email=text(d,'email',150).lower();validate_email(email);throttle(r,'register',5,identity=email);throttle(r,'register-ip',300)
    u=User(username=email,email=email,first_name=text(d,'name',150),role=d['role'])
    password=text(d,'password',128);validate_password(password,u);u.set_password(password);u.save();login(r,u)
    Notification.objects.create(user=u,text='Welcome to Academia Share. Your classroom, connected.')
    return JsonResponse({'user':uj(u)},status=201)
@endpoint(('POST',),public=True)
def signin(r):
    d=payload(r);email=text(d,'email',150).lower();throttle(r,'login',identity=email);u=authenticate(r,username=email,password=d.get('password',''))
    if not u or u.role!=d.get('role'):raise APIError('Email, password, or account type is incorrect.',401)
    login(r,u);return JsonResponse({'user':uj(u)})
@endpoint(('POST',))
def signout(r):logout(r);return JsonResponse({'ok':True})
@endpoint()
def state(r):
    from .exams import exam_json,finalize_expired
    from .calls import call_json
    from .models import Exam,VideoCall
    u=r.user;cs=list(ids(u))
    finalize_expired(Exam.objects.filter(course_id__in=cs).values_list('id',flat=True))
    return JsonResponse({'user':uj(u),
        'courses':[cj(c,u) for c in Course.objects.filter(id__in=cs).select_related('teacher').order_by('id')],
        'folders':[fj(f) for f in Folder.objects.filter(Q(owner=u)|Q(course_id__in=cs,deleted_at__isnull=True))],
        'files':[rj(f,u) for f in Resource.objects.filter(Q(owner=u)|Q(course_id__in=cs,deleted_at__isnull=True)).select_related('owner','folder').order_by('-updated_at')],
        'server_now':timezone.now(),
        'exams':[exam_json(e,u) for e in Exam.objects.filter(course_id__in=cs).filter(Q(course__teacher=u)|Q(appears_at__lte=timezone.now())).select_related('course').order_by('-created_at')],
        'calls':[call_json(c,u) for c in VideoCall.objects.filter(course_id__in=cs).order_by('-created_at')],
        'assignments':[aj(a,u) for a in Assignment.objects.filter(course_id__in=cs).order_by('due')],
        'announcements':[{'id':a.id,'title':a.title,'body':a.body,'course':a.course_id,'author':uj(a.author),'created_at':a.created_at} for a in Announcement.objects.filter(course_id__in=cs).select_related('author').order_by('-created_at')[:100]],
        'activity':[{'id':a.id,'actor':uj(a.actor),'text':a.text,'course':a.course_id,'created_at':a.created_at} for a in Activity.objects.filter(Q(actor=u)|Q(course_id__in=cs)).select_related('actor').order_by('-created_at')[:30]],
        'notifications':list(Notification.objects.filter(user=u,available_at__lte=timezone.now()).order_by('-available_at','-id').values('id','text','read','created_at','available_at','kind','target')[:200]),'storage':{'used':storage(u),'limit':settings.USER_STORAGE_LIMIT}})
@endpoint(('PATCH',))
def profile(r):
    d=payload(r);u=r.user
    u.first_name=text(d,'name',150);u.department=text(d,'department',120,False);u.institution=text(d,'institution',150,False)
    if d.get('new_password'):
        if not u.check_password(d.get('current_password','')):raise APIError('Your current password is incorrect.')
        validate_password(d['new_password'],u);u.set_password(d['new_password']);u.save();update_session_auth_hash(r,u)
    else:u.save()
    return JsonResponse({'user':uj(u)})
@endpoint(('POST',))
def courses(r):
    teacher(r.user);d=payload(r)
    c=Course.objects.create(name=text(d,'name',120),code=text(d,'code',24),description=text(d,'description',4000,False),color=color(d),teacher=r.user)
    Folder.objects.create(name='Class resources',owner=r.user,course=c,color=c.color);activity(r.user,f'created {c.name}',c)
    return JsonResponse(cj(c,r.user),status=201)
@endpoint(('POST',))
def join_course(r):
    if r.user.role!='student':raise APIError('Use a student account to join a class.',403)
    throttle(r,'join',40);c=Course.objects.filter(invite_code=text(payload(r),'code',16).upper()).first()
    if not c:raise APIError('Class code not found. Check the code with your teacher.',404)
    _,created=Membership.objects.get_or_create(course=c,student=r.user)
    if created:activity(r.user,f'joined {c.name}',c);Notification.objects.create(user=c.teacher,text=f'{r.user.first_name} joined {c.name}.'[:255])
    return JsonResponse(cj(c,r.user))
@endpoint()
def course_detail(r,pk):
    c=course(r.user,pk)
    return JsonResponse({'course':cj(c,r.user),'members':[uj(m.student) for m in c.memberships.select_related('student')] if c.teacher_id==r.user.id else []})
@endpoint(('POST',))
def folders(r):
    d=payload(r);p=folder(r.user,d.get('parent'),True);c=course(r.user,d['course'],True) if d.get('course') else (p.course if p else None)
    if c:teacher(r.user)
    if p and p.course_id!=(c.id if c else None):raise APIError('A subfolder must belong to the same class as its parent.')
    name=text(d,'name',120)
    if Folder.objects.filter(owner=r.user,course=c,parent=p,name__iexact=name,deleted_at=None).exists():raise APIError('A folder with that name already exists here.')
    f=Folder.objects.create(name=name,owner=r.user,course=c,parent=p,color=color(d));activity(r.user,f'created the folder “{name}”',c)
    return JsonResponse(fj(f),status=201)
@endpoint(('PATCH','DELETE'))
@transaction.atomic
def folder_detail(r,pk):
    f=Folder.objects.filter(pk=pk,owner=r.user).first()
    if not f:raise APIError('Folder not found.',404)
    if r.method=='DELETE':
        if f.deleted_at:raise APIError('This folder is already in the trash.')
        batch,now=str(uuid.uuid4()),timezone.now();fs=subtree(f)
        Resource.objects.filter(folder_id__in=fs,deleted_at=None).update(deleted_at=now,trash_batch=batch)
        Folder.objects.filter(id__in=fs,deleted_at=None).update(deleted_at=now,trash_batch=batch)
        return JsonResponse({'ok':True})
    d=payload(r)
    if d.get('restore'):
        if f.parent and f.parent.deleted_at and f.parent.trash_batch!=f.trash_batch:raise APIError('Restore the parent folder first.')
        if f.trash_batch:
            Folder.objects.filter(owner=r.user,trash_batch=f.trash_batch).update(deleted_at=None,trash_batch='')
            Resource.objects.filter(owner=r.user,trash_batch=f.trash_batch).update(deleted_at=None,trash_batch='')
        return JsonResponse({'ok':True})
    if f.deleted_at:raise APIError('Restore this folder first.')
    if 'parent' in d:
        p=folder(r.user,d.get('parent'),True)
        if p and (p.id in subtree(f) or p.course_id!=f.course_id):raise APIError('Choose a folder in the same class, outside this folder.')
        f.parent=p
    if 'name' in d:f.name=text(d,'name',120)
    if Folder.objects.filter(owner=r.user,course=f.course,parent=f.parent,name__iexact=f.name,deleted_at=None).exclude(pk=f.pk).exists():raise APIError('A folder with that name already exists here.')
    f.save();return JsonResponse(fj(f))
@endpoint(('POST',))
def files(r):
    f=upload(r);p=folder(r.user,r.POST.get('folder'),True);c=course(r.user,r.POST['course'],True) if r.POST.get('course') else (p.course if p else None)
    if c:teacher(r.user)
    if p and p.course_id!=(c.id if c else None):raise APIError('The file and folder must belong to the same class.')
    obj=Resource.objects.create(name=f.name[:180],owner=r.user,course=c,folder=p,file=f,size=f.size,mime=mimetypes.guess_type(f.name)[0] or 'application/octet-stream',description=r.POST.get('description','')[:4000])
    activity(r.user,f'uploaded {obj.name}',c)
    if c:notify(c,f'New resource in {c.name}: {obj.name}',r.user,kind='resource',target=f'class:{c.id}')
    return JsonResponse(rj(obj,r.user),status=201)
@endpoint(('PATCH','DELETE'))
def file_detail(r,pk):
    f=resource(r.user,pk,True,True);previous_course=f.course_id
    if r.method=='DELETE':f.deleted_at=timezone.now();f.trash_batch=str(uuid.uuid4())
    else:
        d=payload(r)
        if d.get('restore'):
            if f.folder and f.folder.deleted_at:raise APIError('Restore the parent folder first.')
            f.deleted_at=None;f.trash_batch=''
        else:
            if f.deleted_at:raise APIError('Restore this file first.')
            if 'name' in d:
                name=text(d,'name',180)
                if Path(name).suffix.lower()!=Path(f.name).suffix.lower():raise APIError('Keep the original file extension when renaming.')
                f.name=name
            if 'folder' in d or 'course' in d:
                p=folder(r.user,d.get('folder'),True);c=course(r.user,d['course'],True) if d.get('course') else (p.course if p else None)
                if c:teacher(r.user)
                if p and p.course_id!=(c.id if c else None):raise APIError('The file and folder must belong to the same class.')
                f.folder,f.course=p,c
            if 'description' in d:f.description=text(d,'description',4000,False)
    f.save()
    if f.course_id and f.course_id!=previous_course:notify(f.course,f'New resource in {f.course.name}: {f.name}',r.user,kind='resource',target=f'class:{f.course_id}')
    return JsonResponse(rj(f,r.user))
@endpoint(('POST',))
def star(r,pk):
    f=resource(r.user,pk);starred=not f.starred_by.filter(id=r.user.id).exists()
    if starred:f.starred_by.add(r.user)
    else:f.starred_by.remove(r.user)
    return JsonResponse({'starred':starred})
def file_response(field,name,preview=False):
    try:response=FileResponse(field.open('rb'),as_attachment=not preview,filename=name)
    except (FileNotFoundError,ValueError):raise APIError('The stored file is unavailable.',404)
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff'
    if preview:
        response['Content-Security-Policy']="sandbox; default-src 'none'"
        response['X-Frame-Options']='SAMEORIGIN'
    return response
@endpoint()
def download(r,pk):
    f=resource(r.user,pk);preview=r.GET.get('preview')=='1' and (f.mime=='application/pdf' or f.mime.startswith(('image/','text/')))
    return file_response(f.file,f.name,preview)
@endpoint(('POST',))
def assignments(r):
    teacher(r.user);d=payload(r);c=course(r.user,d.get('course'),True);due=parse_datetime(d.get('due',''));points=int(d.get('points',100))
    if not due or timezone.is_naive(due) or due<=timezone.now():raise APIError('Choose a future due date with a timezone.')
    if not 1<=points<=1000:raise APIError('Points must be between 1 and 1000.')
    a=Assignment.objects.create(title=text(d,'title'),description=text(d,'description',10000),course=c,due=due,points=points,allow_late=bool(d.get('allow_late',True)))
    notify(c,f'New assignment: {a.title}',r.user,kind='assignment',target=f'assignment:{a.id}');activity(r.user,f'posted {a.title}',c)
    return JsonResponse(aj(a,r.user),status=201)
@endpoint(('GET','POST'))
def submissions(r,pk):
    a=Assignment.objects.select_related('course').filter(pk=pk).first()
    if not a:raise APIError('Assignment not found.',404)
    course(r.user,a.course_id)
    if r.method=='GET':
        ss=a.submissions.all() if a.course.teacher_id==r.user.id else a.submissions.filter(student=r.user)
        return JsonResponse({'submissions':[sj(s) for s in ss.select_related('student')]})
    if r.user.role!='student':raise APIError('Only students can submit assignments.',403)
    if not a.allow_late and timezone.now()>a.due:raise APIError('The submission deadline has passed.')
    s=Submission.objects.filter(assignment=a,student=r.user).first()
    if s and s.grade is not None:raise APIError('This work is already graded. Contact your teacher to make changes.')
    f=upload(r,s.size if s else 0);old=s.file if s else None
    s,_=Submission.objects.update_or_create(assignment=a,student=r.user,defaults={'file':f,'name':f.name[:180],'size':f.size,'note':r.POST.get('note','')[:10000]})
    if old and old.name!=s.file.name:old.delete(save=False)
    Notification.objects.create(user=a.course.teacher,text=f'{r.user.first_name} submitted {a.title}.'[:255]);activity(r.user,f'submitted {a.title}',a.course)
    return JsonResponse(sj(s),status=201)
@endpoint(('PATCH',))
def submission_detail(r,pk):
    s=Submission.objects.select_related('assignment__course','student').filter(pk=pk).first()
    if not s:raise APIError('Submission not found.',404)
    course(r.user,s.assignment.course_id,True);d=payload(r);grade=int(d.get('grade',-1))
    if not 0<=grade<=s.assignment.points:raise APIError(f'Grade must be between 0 and {s.assignment.points}.')
    s.grade=grade;s.feedback=text(d,'feedback',10000,False);s.save(update_fields=['grade','feedback'])
    Notification.objects.create(user=s.student,text=f'Your work for {s.assignment.title} was graded: {grade}/{s.assignment.points}.'[:255],kind='result',target=f'assignment:{s.assignment_id}')
    return JsonResponse(sj(s))
@endpoint()
def submission_download(r,pk):
    s=Submission.objects.select_related('assignment__course').filter(pk=pk).first()
    if not s or (s.student_id!=r.user.id and s.assignment.course.teacher_id!=r.user.id):raise APIError('Submission not found.',404)
    return file_response(s.file,s.name)
@endpoint(('POST',))
def announcements(r):
    teacher(r.user);d=payload(r);c=course(r.user,d.get('course'),True)
    a=Announcement.objects.create(title=text(d,'title'),body=text(d,'body',10000),course=c,author=r.user);notify(c,f'{c.name}: {a.title}',r.user,kind='announcement',target='announcements')
    return JsonResponse({'id':a.id},status=201)
@endpoint(('POST',))
def notifications_read(r):
    records=Notification.objects.filter(user=r.user,read=False,available_at__lte=timezone.now())
    d=payload(r)
    if 'id' in d:records=records.filter(pk=int(d['id']))
    records.update(read=True)
    return JsonResponse({'ok':True})
@endpoint(('POST',))
@transaction.atomic
def empty_trash(r):
    Resource.objects.filter(owner=r.user,deleted_at__isnull=False).delete();Folder.objects.filter(owner=r.user,deleted_at__isnull=False).delete()
    return JsonResponse({'ok':True})
@endpoint(public=True)
def health(r):
    from django.db import connection,DatabaseError
    from .models import ServiceHeartbeat
    ready=True;checks={}
    try:
        with connection.cursor() as cursor:cursor.execute('SELECT 1');cursor.fetchone()
        checks['database']='ready'
        if settings.SCHEDULER_REQUIRED:
            heartbeat=ServiceHeartbeat.objects.filter(name='exam-scheduler').first()
            fresh=heartbeat and (timezone.now()-heartbeat.updated_at).total_seconds()<75
            checks['scheduler']='ready' if fresh else 'unavailable'
            ready=ready and bool(fresh)
        else:checks['scheduler']='optional'
    except DatabaseError:
        checks['database']='unavailable';ready=False
    writable=Path(settings.MEDIA_ROOT).is_dir() and os.access(settings.MEDIA_ROOT,os.W_OK)
    checks['storage']='ready' if writable else 'unavailable';ready=ready and writable
    return JsonResponse({'status':'ok' if ready else 'unavailable','app':'Academia Share','version':'1.2.0',**checks},status=200 if ready else 503)
def csrf_failure(r,reason=''):return JsonResponse({'error':'Your security token expired. Refresh the page and try again.'},status=403)
def api_not_found(r):return JsonResponse({'error':'API endpoint not found.'},status=404)
def frontend(r):
    index=settings.FRONTEND_DIST/'index.html'
    if not index.exists():return HttpResponse('Build the frontend with npm run build first.',status=503)
    return HttpResponse(index.read_text(),content_type='text/html')
def favicon(r):return FileResponse((settings.BASE_DIR.parent/'public'/'favicon.svg').open('rb'),content_type='image/svg+xml')
