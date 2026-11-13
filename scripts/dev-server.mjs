// One development command, with React and the real Django API in the same environment.
import {spawn,spawnSync} from 'node:child_process';
import {existsSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
const root=process.cwd(),backend=resolve(root,'backend');
const python=resolve(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
if(!existsSync(python)){process.stderr.write('Run python start.py --setup-only first to install the backend.\n');process.exit(1);}
const environment={...process.env,DJANGO_ENV:'development',DJANGO_DEBUG:'1',DJANGO_CSRF_ORIGINS:'http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173'};
mkdirSync(resolve(environment.ACADEMIA_DATA_DIR||backend,'media'),{recursive:true});
const migrated=spawnSync(python,['manage.py','migrate','--noinput'],{cwd:backend,env:environment,stdio:'inherit'});
if(migrated.status!==0)process.exit(migrated.status||1);
const children=[spawn(python,['-m','waitress','--listen=127.0.0.1:8000','academia.wsgi:application'],{cwd:backend,env:environment,stdio:'inherit'}),spawn(python,['manage.py','run_exam_scheduler'],{cwd:backend,env:environment,stdio:'inherit'}),spawn(process.execPath,[resolve(root,'node_modules/vite/bin/vite.js'),'--host','0.0.0.0',...process.argv.slice(2)],{cwd:root,env:environment,stdio:'inherit'})];
let stopping=false;
function stop(){if(stopping)return;stopping=true;for(const child of children)child.kill('SIGTERM');}
process.on('SIGINT',stop);process.on('SIGTERM',stop);
for(const child of children){child.on('error',error=>{process.stderr.write(error.message+'\n');stop();process.exitCode=1;});child.on('exit',code=>{if(!stopping){stop();process.exitCode=code||1;}});}
