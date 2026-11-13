import logging
import signal
from threading import Event
from django.core.management.base import BaseCommand,CommandError
from django.db import close_old_connections,DatabaseError
from django.utils import timezone
from core.exams import finalize_expired
from core.models import ServiceHeartbeat

logger=logging.getLogger(__name__)

class Command(BaseCommand):
    help='Finalize expired exams independently of browsers and publish a health heartbeat.'
    def add_arguments(self,parser):
        parser.add_argument('--interval',type=int,default=15)
        parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        interval=options['interval']
        if not 1<=interval<=30:raise CommandError('Interval must be between 1 and 30 seconds.')
        stopped=Event()
        if not options['once']:
            for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:stopped.set())
        while not stopped.is_set():
            close_old_connections()
            try:
                finalize_expired(limit=200)
                ServiceHeartbeat.objects.update_or_create(name='exam-scheduler',defaults={'updated_at':timezone.now()})
                if options['once']:self.stdout.write('Expired exams finalized; scheduler heartbeat updated.')
            except DatabaseError:
                logger.exception('Exam scheduler database operation failed; it will retry.')
                if options['once']:raise
            finally:close_old_connections()
            if options['once']:return
            stopped.wait(interval)
