import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from .schemas import State, TERMINAL
from .security import Vault

def now():return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self,root):
        root.mkdir(parents=True,exist_ok=True)
        self.vault=Vault(root/'sealed')
        self.db=sqlite3.connect(root/'liquidpilot.sqlite3',check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.lock=threading.RLock()
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        PRAGMA secure_delete=ON;
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,state TEXT NOT NULL,created TEXT,updated TEXT,payload TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,at TEXT,kind TEXT,payload TEXT);
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,url_hash TEXT,payload TEXT,UNIQUE(task_id,url_hash));
        CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,name TEXT,mime TEXT,size INTEGER,sealed_name TEXT);
        CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,payload TEXT,sealed_name TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS public_fts USING fts5(task_id UNINDEXED,source_id UNINDEXED,url,title,content);
        ''')
        self.db.commit()

    def create(self,spec):
        ident=uuid4().hex
        payload={'spec':spec.model_dump(),'plan':None,'outcome':None,'pending_approval':None,'step':0,'issues':[], 'active_url':'', 'metrics':{}, 'paused':False}
        with self.lock,self.db:
            self.db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)',(ident,State.CREATED,now(),now(),self.vault.encrypt(payload)))
        self.event(ident,'state',{'state':State.CREATED,'message':'Task created.'})
        return self.get(ident)

    def get(self,ident):
        row=self.db.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone()
        if not row:raise KeyError(ident)
        return {k:row[k] for k in ('id','state','created','updated')}|self.vault.decrypt(row['payload'])

    def list(self):
        return [self.get(row['id']) for row in self.db.execute('SELECT id FROM tasks ORDER BY created DESC LIMIT 100')]

    def update(self,ident,**changes):
        with self.lock,self.db:
            task=self.get(ident)
            state=changes.pop('state',task['state'])
            if task['state'] in TERMINAL and state!=task['state']:
                raise ValueError('A finished task cannot be restarted; clone it as a new task.')
            for key in ('id','created','updated','state'):task.pop(key,None)
            task.update(changes)
            self.db.execute('UPDATE tasks SET state=?,updated=?,payload=? WHERE id=?',(state,now(),self.vault.encrypt(task),ident))
        return self.get(ident)

    def transition(self,ident,state,message):
        current=self.get(ident)['state']
        if current==state:return
        self.update(ident,state=state)
        self.event(ident,'state',{'state':state,'message':message})

    def event(self,ident,kind,payload):
        with self.lock,self.db:
            cursor=self.db.execute('INSERT INTO events(task_id,at,kind,payload) VALUES(?,?,?,?)',(ident,now(),kind,self.vault.encrypt(payload)))
            return cursor.lastrowid

    def events(self,ident,after=0):
        return [{'id':r['id'],'at':r['at'],'kind':r['kind'],**self.vault.decrypt(r['payload'])} for r in self.db.execute('SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id LIMIT 500',(ident,after))]

    def add_source(self,ident,source,remember=False):
        import hashlib
        url_hash=hashlib.sha256(source['url'].encode()).hexdigest()
        existing=self.db.execute('SELECT id FROM sources WHERE task_id=? AND url_hash=?',(ident,url_hash)).fetchone()
        if existing:return existing['id']
        sid=uuid4().hex
        with self.lock,self.db:
            self.db.execute('INSERT INTO sources VALUES(?,?,?,?)',(sid,ident,url_hash,self.vault.encrypt(source)))
            if remember:
                self.db.execute('INSERT INTO public_fts VALUES(?,?,?,?,?)',(ident,sid,source['url'],source['title'],'\n'.join(source.get('chunks',[]))))
        return sid

    def sources(self,ident):
        return [{'id':r['id'],**self.vault.decrypt(r['payload'])} for r in self.db.execute('SELECT * FROM sources WHERE task_id=?',(ident,))]

    def search(self,query):
        import re
        tokens=re.findall(r'[\w-]+',query)[:12]
        if not tokens:return []
        expression=' OR '.join('"'+x.replace('"','')+'"' for x in tokens)
        rows=self.db.execute('SELECT task_id,source_id,url,title,snippet(public_fts,4,"","","…",35) AS excerpt FROM public_fts WHERE public_fts MATCH ? ORDER BY rank LIMIT 15',(expression,))
        return [dict(r) for r in rows]

    def artifact(self,ident,name,mime,data):
        aid=uuid4().hex
        sealed_name=aid+'.sealed'
        self.vault.file(sealed_name,data)
        with self.lock,self.db:self.db.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?)',(aid,ident,name,mime,len(data),sealed_name))
        return {'id':aid,'name':name,'mime':mime,'size':len(data)}

    def artifacts(self,ident):
        return [dict(r) for r in self.db.execute('SELECT id,name,mime,size FROM artifacts WHERE task_id=?',(ident,))]

    def read_artifact(self,aid):
        row=self.db.execute('SELECT * FROM artifacts WHERE id=?',(aid,)).fetchone()
        if not row:raise KeyError(aid)
        return dict(row),self.vault.file(row['sealed_name'])

    def upload(self,name,mime,data,extracted):
        ident=uuid4().hex
        sealed=ident+'.sealed'
        self.vault.file(sealed,data)
        payload={'name':name,'mime':mime,'size':len(data),'extracted':extracted,'created':now()}
        with self.lock,self.db:self.db.execute('INSERT INTO uploads VALUES(?,?,?)',(ident,self.vault.encrypt(payload),sealed))
        return {'id':ident,'name':name,'size':len(data),'kind':extracted['kind']}

    def get_upload(self,ident):
        row=self.db.execute('SELECT * FROM uploads WHERE id=?',(ident,)).fetchone()
        if not row:raise KeyError(ident)
        return self.vault.decrypt(row['payload']),self.vault.file(row['sealed_name'])

    def forget(self,ident):
        self.get(ident)
        with self.lock,self.db:
            paths=[r['sealed_name'] for r in self.db.execute('SELECT sealed_name FROM artifacts WHERE task_id=?',(ident,))]
            self.db.execute('DELETE FROM public_fts WHERE task_id=?',(ident,))
            self.db.execute('DELETE FROM tasks WHERE id=?',(ident,))
        for name in paths:(self.vault.root/name).unlink(missing_ok=True)

    def recover_interrupted(self):
        for task in self.list():
            if task['state'] not in TERMINAL:
                self.update(task['id'],state=State.PAUSED,pending_approval=None,paused=True)
                self.event(task['id'],'recovery',{'message':'Application restarted. Browser state and pending approval were discarded. Resume creates a new read-only task; submitted actions are never replayed.'})

    def expire(self,days):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        for row in self.db.execute('SELECT id FROM tasks WHERE updated<? AND state IN (?,?,?,?)',(cutoff,*TERMINAL)).fetchall():self.forget(row['id'])

    def close(self):self.db.close()
