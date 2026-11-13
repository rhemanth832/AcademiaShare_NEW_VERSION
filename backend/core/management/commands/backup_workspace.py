"""Consistent SQLite snapshot plus private media, for administrator-run backups."""
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.utils import timezone

class Command(BaseCommand):
    help='Create a private backup of SQLite and uploaded media; copy it off-host for disaster recovery.'
    def add_arguments(self,parser):parser.add_argument('--output',type=str)
    def handle(self,*args,**options):
        if settings.DATABASES['default']['ENGINE']!='django.db.backends.sqlite3':raise CommandError('This backup command supports SQLite only.')
        database=Path(settings.DATABASES['default']['NAME'])
        if not database.is_file():raise CommandError('Database does not exist.')
        settings.BACKUP_ROOT.mkdir(parents=True,exist_ok=True)
        output=Path(options['output']) if options['output'] else settings.BACKUP_ROOT/f'workspace-{timezone.now():%Y%m%d-%H%M%S-%f}.zip'
        output=output.resolve()
        if output.exists():raise CommandError('The output already exists. Choose a new filename.')
        output.parent.mkdir(parents=True,exist_ok=True)
        handle=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        manifest={'version':1,'created_at':timezone.now().isoformat(),'files':{}}
        try:
            with os.fdopen(handle,'wb') as destination,tempfile.TemporaryDirectory() as temporary:
                snapshot=Path(temporary)/'db.sqlite3'
                with sqlite3.connect(database) as source,sqlite3.connect(snapshot) as target:source.backup(target)
                with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
                    with sqlite3.connect(snapshot) as saved:
                        names=[row[0] for row in saved.execute("SELECT file FROM core_resource UNION SELECT file FROM core_submission") if row[0]]
                    paths=[('db.sqlite3',snapshot)]
                    for name in names:
                        relative=Path(name)
                        path=(settings.MEDIA_ROOT/relative).resolve()
                        if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(settings.MEDIA_ROOT.resolve()):
                            raise CommandError('A stored upload has an invalid path.')
                        paths.append((f'media/{relative.as_posix()}',path))
                    for name,path in paths:
                        try:
                            digest=hashlib.sha256()
                            with path.open('rb') as source,archive.open(name,'w') as member:
                                for block in iter(lambda:source.read(1024*1024),b''):
                                    member.write(block);digest.update(block)
                            manifest['files'][name]=digest.hexdigest()
                        except FileNotFoundError:
                            raise CommandError('A referenced upload was removed during backup. Retry during a quiet period.')
                    archive.writestr('manifest.json',json.dumps(manifest,indent=2))
            self.stdout.write(str(output))
        except BaseException:
            output.unlink(missing_ok=True)
            raise
