"""Start the real React + Django + SQLite application locally. No example accounts are created."""
import argparse,os,shutil,subprocess,sys,venv,webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description='Set up and start Academia Share')
parser.add_argument('--setup-only',action='store_true',help='Prepare the app without starting the server')
parser.add_argument('--port',type=int,default=8000)
args=parser.parse_args()
if not 1<=args.port<=65535:parser.error('Choose a port between 1 and 65535.')
python=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
if not npm:sys.exit('Install Node.js 20.19+ or 22.12+ first, then run python start.py again.')
if sys.version_info<(3,10):sys.exit('Python 3.10 or later is required.')
def run(command,cwd=ROOT):subprocess.run([str(x) for x in command],cwd=cwd,check=True)
worker=None
try:
    if not python.exists():venv.create(ROOT/'.venv',with_pip=True)
    run([python,'-m','pip','install','-r',ROOT/'backend/requirements.txt'])
    run([npm,'ci']);run([npm,'run','build'])
    data=Path(os.environ.get('ACADEMIA_DATA_DIR',str(ROOT/'backend')))
    (data/'media').mkdir(parents=True,exist_ok=True)
    run([python,'manage.py','migrate','--noinput'],cwd=ROOT/'backend')
    run([python,'manage.py','collectstatic','--noinput'],cwd=ROOT/'backend')
    if not args.setup_only:
        worker=subprocess.Popen([str(python),'manage.py','run_exam_scheduler'],cwd=ROOT/'backend')
        url=f'http://127.0.0.1:{args.port}'
        print(f'\nAcademia Share is ready: {url}\nCreate your own teacher and student accounts. Press Ctrl+C to stop.\n',flush=True)
        webbrowser.open(url)
        run([python,'-m','waitress',f'--listen=127.0.0.1:{args.port}','academia.wsgi:application'],cwd=ROOT/'backend')
except KeyboardInterrupt:print('\nWorkspace stopped. Accounts and files remain saved.')
except subprocess.CalledProcessError as error:sys.exit(f'Setup stopped with exit code {error.returncode}. Review the error above.')
finally:
    if worker and worker.poll() is None:
        worker.terminate()
        try:worker.wait(timeout=5)
        except subprocess.TimeoutExpired:worker.kill()
