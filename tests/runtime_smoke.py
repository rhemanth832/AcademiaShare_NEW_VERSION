"""Exercise the actual production supervisor, independent clients, and restart persistence.
Run after installing backend requirements and building React:
    .venv/bin/python tests/runtime_smoke.py
All accounts, uploads, secrets, and SQLite files are temporary test fixtures.
"""
import base64
import datetime
import hashlib
import http.cookies
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
UTC=datetime.timezone.utc

class Client:
    def __init__(self,port):
        self.port=port;self.cookies={};self.last_cookie_flags={}
    def request(self,path,method='GET',data=None,raw=None,content_type=None,expected=200):
        headers={'Accept':'application/json','Host':'campus.example.test','X-Forwarded-Proto':'https'}
        if self.cookies:headers['Cookie']='; '.join(f'{k}={v}' for k,v in self.cookies.items())
        if method!='GET':
            token=self.request('auth/csrf/')['csrfToken']
            headers['X-CSRFToken']=token;headers['Origin']='https://campus.example.test'
            headers['Cookie']='; '.join(f'{k}={v}' for k,v in self.cookies.items())
            headers['Content-Type']=content_type or 'application/json'
        payload=raw if raw is not None else json.dumps(data or {}).encode() if method!='GET' else None
        request=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/{path}',headers=headers,data=payload,method=method)
        try:response=urllib.request.urlopen(request,timeout=10)
        except urllib.error.HTTPError as error:response=error
        with response:
            for header in response.headers.get_all('Set-Cookie',[]):
                jar=http.cookies.SimpleCookie();jar.load(header)
                for key,morsel in jar.items():
                    self.cookies[key]=morsel.value;self.last_cookie_flags[key]={'secure':bool(morsel['secure']),'httponly':bool(morsel['httponly'])}
            content=response.read()
            if response.status!=expected:
                raise AssertionError(f'{method} {path}: expected {expected}, received {response.status}: {content[:500]!r}')
            return json.loads(content) if 'application/json' in response.headers.get('Content-Type','') else content
    def register(self,role):
        return self.request('auth/register/','POST',{'name':role.title()+' Runtime Test','email':role+'@runtime.example.test','role':role,'password':secrets.token_urlsafe(22)},expected=201)['user']
    def upload(self,path,filename,content,fields):
        boundary='AcademiaBoundary'+secrets.token_hex(16)
        chunks=[]
        for key,value in fields.items():chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: text/plain\r\n\r\n'.encode()+content+f'\r\n--{boundary}--\r\n'.encode())
        return self.request(path,'POST',raw=b''.join(chunks),content_type=f'multipart/form-data; boundary={boundary}',expected=201)

def main():
    if not (ROOT/'dist'/'index.html').exists():raise RuntimeError('Run npm run build first.')
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='academia-runtime-') as temp:
        data=Path(temp)/'data'
        env={**os.environ,'DJANGO_ENV':'production','DJANGO_DEBUG':'0','DJANGO_SECRET_KEY':base64.b64encode(secrets.token_bytes(32)).decode(),
             'DJANGO_ALLOWED_HOSTS':'campus.example.test,localhost,127.0.0.1','DJANGO_CSRF_ORIGINS':'https://campus.example.test',
             'DJANGO_TRUST_PROXY':'1','ACADEMIA_DATA_DIR':str(data),'ACADEMIA_SCHEDULER_REQUIRED':'1',
             'ACADEMIA_DROP_PRIVILEGES':'0','PORT':str(port)}
        process=None
        log_path=Path(temp)/'server.log'
        log=log_path.open('w')
        def start():
            nonlocal process
            process=subprocess.Popen([sys.executable,'ops/run_server.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            client=Client(port)
            for _ in range(240):
                if process.poll() is not None:raise RuntimeError('Production server exited during startup.')
                try:
                    if client.request('health/')['status']=='ok':return
                except (OSError,AssertionError):pass
                time.sleep(.1)
            raise RuntimeError('Production server did not become ready.')
        def stop():
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=30)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
        try:
            start()
            teacher,student,outsider=Client(port),Client(port),Client(port)
            assert teacher.request('state/',expected=401)
            tu=teacher.register('teacher');su=student.register('student')
            assert teacher.last_cookie_flags['sessionid']=={'secure':True,'httponly':True}
            assert teacher.request('state/')['courses']==[]
            c=teacher.request('courses/','POST',{'name':'Runtime classroom','code':'REAL-101'},expected=201)
            student.request('courses/join/','POST',{'code':c['invite_code']})
            folder=teacher.request('folders/','POST',{'name':'Shared lessons','course':c['id']},expected=201)
            nested=teacher.request('folders/','POST',{'name':'Week 1','course':c['id'],'parent':folder['id']},expected=201)
            content=b'Real persistent classroom resource.\n'
            file=teacher.upload('files/','lesson.txt',content,{'course':c['id'],'folder':nested['id']})
            student.request('files/'+str(file['id'])+'/download/')==content
            outsider.request('files/'+str(file['id'])+'/download/',expected=401)
            teacher.request('announcements/','POST',{'course':c['id'],'title':'Class update','body':'The lesson is available.'},expected=201)
            now=datetime.datetime.now(UTC)
            assignment=teacher.request('assignments/','POST',{'course':c['id'],'title':'Class work','description':'Upload a text file.','due':(now+datetime.timedelta(hours=1)).isoformat(),'points':10},expected=201)
            submitted=student.upload(f'assignments/{assignment["id"]}/submissions/','answer.txt',b'My class work',{'note':'Completed'})
            teacher.request(f'submissions/{submitted["id"]}/','PATCH',{'grade':8,'feedback':'Good work.'})
            exam=teacher.request('exams/','POST',{'course':c['id'],'title':'Server-timed exam','appears_at':(now-datetime.timedelta(minutes=1)).isoformat(),'starts_at':(now-datetime.timedelta(seconds=30)).isoformat(),
                'deadline':(now+datetime.timedelta(seconds=20)).isoformat(),'duration_minutes':1,'results_mode':'immediate',
                'questions':[{'text':'FIFO?','options':['Queue','Stack'],'correct':0,'points':3}]},expected=201)
            question=teacher.request(f'exams/{exam["id"]}/')['exam']['questions'][0]
            attempt=student.request(f'exams/{exam["id"]}/start/','POST')['attempt']
            assert attempt['expires_at']==exam['deadline']
            assert 'correct' not in student.request(f'exams/{exam["id"]}/')['exam']['questions'][0]
            student.request(f'exams/{exam["id"]}/answers/','PATCH',{'answers':{question['id']:0}})
            call=teacher.request('calls/','POST',{'course':c['id'],'title':'Class video session','starts_at':now.isoformat(),'start_now':True},expected=201)
            assert student.request(f'calls/{call["id"]}/join/','POST')['join_url'].startswith('https://meet.jit.si/')
            teacher.request(f'calls/{call["id"]}/end/','POST')
            # Do not call app state/results/exam routes while waiting: only the worker can finalize it.
            for _ in range(200):
                with sqlite3.connect(data/'db.sqlite3') as database:
                    completed=database.execute('SELECT submitted_at,score,completion FROM core_examattempt WHERE id=?',(attempt['id'],)).fetchone()
                if completed and completed[0]:break
                time.sleep(.25)
            else:raise AssertionError('The independent exam scheduler did not finalize the attempt.')
            assert completed[1:]==(3,'timeout')
            late=student.request(f'exams/{exam["id"]}/answers/','POST',{'answers':{question['id']:1}})['attempt']
            assert late['score']==3
            assert teacher.request(f'exams/{exam["id"]}/results/')['summary']['submitted']==1
            before=student.request('state/')
            assert {'announcement','assignment','resource','exam','result','call'}<={n['kind'] for n in before['notifications']}
            stop();start()
            after=student.request('state/')
            assert after['user']['id']==su['id']
            assert after['courses'][0]['id']==c['id']
            assert after['assignments'][0]['my_submission']['grade']==8
            assert after['exams'][0]['my_attempt']['score']==3
            assert student.request(f'files/{file["id"]}/download/')==content
            assert teacher.request(f'courses/{c["id"]}/analytics/')['students'][0]['student']['id']==su['id']
            output=Path(temp)/'backup.zip'
            subprocess.run([sys.executable,'backend/manage.py','backup_workspace','--output',str(output)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,check=True)
            with zipfile.ZipFile(output) as archive:
                manifest=json.loads(archive.read('manifest.json'))
                for name,digest in manifest['files'].items():assert hashlib.sha256(archive.read(name)).hexdigest()==digest
                assert any(name.startswith('media/') for name in archive.namelist())
                assert archive.testzip() is None
            assert output.stat().st_mode&0o777==0o600
            print(json.dumps({'result':'passed','mode':'production Django/Gunicorn/SQLite','independent_accounts':True,'secure_cookies':True,'cross_account_sharing':True,'worker_timeout_without_requests':True,'restart_preserves_sessions_files_exams_grades':True,'backup_integrity':True}))
        except BaseException:
            log.flush();print(log_path.read_text()[-6000:],file=sys.stderr);raise
        finally:stop();log.close()

if __name__=='__main__':main()
