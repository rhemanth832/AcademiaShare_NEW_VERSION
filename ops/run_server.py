"""One persistent service: startup migrations, exam worker, and the Django WSGI server."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
BACKEND=ROOT/'backend'

def prepare_storage():
    data=Path(os.environ.get('ACADEMIA_DATA_DIR',str(BACKEND))).resolve()
    dirs=[data,data/'media',data/'backups']
    for directory in dirs:directory.mkdir(parents=True,exist_ok=True)
    # New mounted disks can belong to root. Application processes run as UID 10001.
    if hasattr(os,'getuid') and os.getuid()==0 and os.environ.get('ACADEMIA_DROP_PRIVILEGES')=='1':
        for directory in dirs:os.chown(directory,10001,10001)
        for name in ['db.sqlite3','db.sqlite3-wal','db.sqlite3-shm']:
            item=data/name
            if item.exists():os.chown(item,10001,10001)
        os.setgroups([]);os.setgid(10001);os.setuid(10001)
    if not os.access(data,os.W_OK) or not os.access(data/'media',os.W_OK):
        raise RuntimeError('The persistent data directory is not writable by the application user.')

def command(*args):
    subprocess.run([sys.executable,'manage.py',*args],cwd=BACKEND,check=True)

def main():
    prepare_storage()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','academia.settings')
    sys.path.insert(0,str(BACKEND))
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection,connections
    if settings.PRODUCTION and settings.DEBUG:raise RuntimeError('Production must use DJANGO_DEBUG=0.')
    # One instance owns this SQLite volume; take an exclusive startup lock.
    import fcntl
    with (settings.DATA_ROOT/'.startup.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        command('migrate','--noinput')
        command('createcachetable')
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA journal_mode=WAL')
        connections.close_all()
        command('collectstatic','--noinput')
        if settings.PRODUCTION:command('check','--deploy','--fail-level','WARNING')
        command('run_exam_scheduler','--once')
    port=int(os.environ.get('PORT','8000'))
    if not 1<=port<=65535:raise RuntimeError('PORT must be a valid TCP port.')
    scheduler=subprocess.Popen([sys.executable,'manage.py','run_exam_scheduler'],cwd=BACKEND,start_new_session=True)
    server=subprocess.Popen([sys.executable,'-m','gunicorn','academia.wsgi:application',
        '--bind',f'0.0.0.0:{port}','--workers','1','--threads','4','--worker-class','gthread',
        '--timeout','120','--graceful-timeout','20','--keep-alive','5','--max-requests','2000',
        '--max-requests-jitter','100','--access-logfile','-','--error-logfile','-'],cwd=BACKEND,start_new_session=True)
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
        for child in [server,scheduler]:
            if child.poll() is None:
                try:os.killpg(child.pid,signal.SIGTERM)
                except ProcessLookupError:pass
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while not stopping and server.poll() is None and scheduler.poll() is None:time.sleep(.25)
        unexpected=not stopping
        stop()
        for child in [server,scheduler]:
            try:child.wait(timeout=25)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        return 1 if unexpected else 0
    finally:stop()

if __name__=='__main__':
    try:sys.exit(main())
    except KeyboardInterrupt:sys.exit(0)
