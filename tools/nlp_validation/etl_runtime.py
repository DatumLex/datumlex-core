"""Local execution ledger and OS locks; no source content or secrets in state."""
from contextlib import ExitStack, contextmanager
from datetime import datetime,timezone
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid

def now():return datetime.now(timezone.utc).isoformat()

def atomic_bytes(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.part')
    with temporary.open('wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)

def archive_bytes(path,raw):
    path=Path(path)
    if path.exists():
        previous=path.read_bytes()
        if previous==raw:return
        # Preserve damaged/interrupted bytes before repairing the canonical artifact.
        quarantine=path.with_name(path.name+'.corrupt-'+hashlib.sha256(previous).hexdigest()[:16])
        atomic_bytes(quarantine,previous)
    atomic_bytes(path,raw)

def atomic_json(path,value):
    atomic_bytes(path,json.dumps(value,ensure_ascii=False,indent=2).encode('utf8'))

@contextmanager
def file_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    stream=path.open('a+b');stream.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:stream.close()

def owned_run(arguments,backend,stdout,stderr,timeout):
    options={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
    environment={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
    process=subprocess.Popen([sys.executable,'-u',*arguments],cwd=backend,stdout=stdout,stderr=stderr,env=environment,**options)
    def stop():
        if process.poll() is not None:return
        if os.name=='nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
        else:
            import signal
            os.killpg(process.pid,signal.SIGKILL)
        process.wait()
    try:return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop();return 1
    except BaseException:
        stop();raise


class Runtime:
    def __init__(self,backend,mode):
        self.backend=Path(backend);self.root=self.backend/'data/operations';self.mode=mode
        self.id=str(uuid.uuid4());self.stack=ExitStack();self.db=None
        self.state={'job_id':self.id,'mode':mode,'status':'running','started_at':now(),'steps':[]}
    def __enter__(self):
        roles=('collect','process') if self.mode=='all' else (self.mode,)
        try:
            for role in roles:self.stack.enter_context(file_lock(self.root/('etl-'+role+'.lock')))
            self.db=sqlite3.connect(self.root/'etl-state.sqlite3',timeout=30)
            self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,mode TEXT,status TEXT,started_at TEXT,finished_at TEXT)')
            self.db.execute('CREATE TABLE IF NOT EXISTS stages (id INTEGER PRIMARY KEY,job_id TEXT,name TEXT,status TEXT,started_at TEXT,finished_at TEXT,exit_code INTEGER,stdout_log TEXT,stderr_log TEXT)')
            with self.db:
                if self.mode=='all':self.db.execute("UPDATE jobs SET status='interrupted',finished_at=? WHERE status='running'",(now(),))
                else:self.db.execute("UPDATE jobs SET status='interrupted',finished_at=? WHERE status='running' AND mode IN (?,'all')",(now(),self.mode))
                self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,NULL)',(self.id,self.mode,'running',now()))
            self.publish();return self
        except Exception:
            self.stack.close();raise
    def publish(self,**values):
        self.state.update(values);atomic_json(self.root/('etl-'+self.mode+'.json'),self.state)
    def run(self,name,arguments,timeout=7200):
        # Keep originals on D: and preserve minimum system-drive headroom too.
        if shutil.disk_usage(self.root).free<1_000_000_000:raise RuntimeError('Low artifact disk space')
        if os.name=='nt' and shutil.disk_usage(os.environ.get('SystemDrive','C:')+'/').free<1_000_000_000:raise RuntimeError('Low system disk space')
        logs=self.root/'etl-logs'/self.id;logs.mkdir(parents=True,exist_ok=True)
        slug=re.sub('[^a-zA-Z0-9_-]','_',name)
        index=len(self.state['steps']);out=logs/f'{index:03}-{slug}.stdout.log';err=logs/f'{index:03}-{slug}.stderr.log'
        with self.db:
            cursor=self.db.execute('INSERT INTO stages(job_id,name,status,started_at,stdout_log,stderr_log) VALUES (?,?,?,?,?,?)',
                (self.id,name,'running',now(),str(out),str(err)))
        self.publish(phase=name)
        try:
            with out.open('wb') as stdout,err.open('wb') as stderr:
                code=owned_run(arguments,self.backend,stdout,stderr,timeout)
        except (OSError,subprocess.TimeoutExpired):code=1
        status='completed' if code==0 else 'failed'
        with self.db:self.db.execute('UPDATE stages SET status=?,finished_at=?,exit_code=? WHERE id=?',(status,now(),code,cursor.lastrowid))
        self.state['steps'].append({'name':name,'status':status,'exit_code':code,'stdout_log':str(out),'stderr_log':str(err)})
        self.publish();print(json.dumps({'job_id':self.id,'step':name,'status':status,'exit_code':code}),flush=True)
        return code
    def finish(self,status):
        self.publish(status=status,finished_at=now())
        with self.db:self.db.execute('UPDATE jobs SET status=?,finished_at=? WHERE id=?',(status,now(),self.id))
    def __exit__(self,kind,value,traceback):
        if kind:self.finish('interrupted' if issubclass(kind,KeyboardInterrupt) else 'failed')
        elif self.state['status']=='running':self.finish('partial_failure' if any(step['status']=='failed' for step in self.state['steps']) else 'completed')
        if self.db:self.db.close()
        self.stack.close()
