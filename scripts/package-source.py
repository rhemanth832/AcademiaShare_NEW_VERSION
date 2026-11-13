"""Create a clean, reproducible source download without local accounts or uploads."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib,json
root=Path(__file__).resolve().parent.parent
output=root/'public'/'Academia-Share-Source.zip'
root_files={'README.md','VALIDATION.md','THIRD_PARTY_NOTICES.txt','start.py','index.html','vite.config.js','package.json','package-lock.json','.gitignore','Dockerfile','.dockerignore','.env.example','render.yaml','compose.yaml','DEPLOYMENT.md'}
files=[root/name for name in root_files if (root/name).is_file()]
for directory in ['src','scripts','backend','public','ops','tests']:
    for p in (root/directory).rglob('*'):
        if not p.is_file() or p==output:continue
        rel=p.relative_to(root)
        if any(part in {'__pycache__','media','staticfiles','backups','node_modules','.venv','.git'} for part in rel.parts):continue
        if p.suffix.lower() in {'.py','.jsx','.js','.css','.mjs','.svg','.txt'}:files.append(p)
with ZipFile(output,'w',ZIP_DEFLATED,compresslevel=9) as archive:
    for p in sorted(set(files)):
        archive.write(p,Path('Academia-Share')/p.relative_to(root))
with ZipFile(output) as archive:
    assert archive.testzip() is None
    names=archive.namelist()
    assert 'Academia-Share/backend/core/migrations/0001_initial.py' in names
    assert 'Academia-Share/src/main.jsx' in names
    assert not any('db.sqlite3' in n or '/media/' in n or '.env.local' in n for n in names)
print(json.dumps({'file':str(output),'files':len(files),'size':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
