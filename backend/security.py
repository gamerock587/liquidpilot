"""Independent capability checks, DNS-pinned egress proxy, and encrypted persistence."""
import asyncio
import ctypes
from ctypes import wintypes
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
from urllib.parse import urlsplit
from cryptography.fernet import Fernet

class PolicyError(ValueError):
    pass

def redact(value: str):
    value = re.sub(r'(?i)((?:password|authorization|api[_-]?key|access[_-]?token|session[_-]?token|cookie)\s*[:=]\s*)[^\s,;]+', r'\1[REDACTED]', value)
    return re.sub(r'(?i)Bearer\s+[A-Za-z0-9._-]+', 'Bearer [REDACTED]', value)

def origin(url):
    p=urlsplit(url)
    host=p.hostname or ''
    if ':' in host: host=f'[{host}]'
    port=p.port or (443 if p.scheme=='https' else 80)
    return f'{p.scheme}://{host}:{port}'

def normalize_url(url):
    p=urlsplit(url)
    return p._replace(fragment='').geturl().rstrip('/')

class Policy:
    def __init__(self, spec, private_origins=()):
        self.spec=spec
        self.private_origins={origin(x) for x in private_origins}
        self.blocked=[]
        self.created=__import__('time').monotonic()

    async def resolve(self, url, scoped=True):
        p=urlsplit(url)
        if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password:
            raise PolicyError('Only HTTP(S) URLs without credentials are allowed.')
        if p.port and p.port not in {80,443} and origin(url) not in self.private_origins:
            raise PolicyError('Nonstandard ports require an explicit private-origin grant.')
        host=p.hostname.lower().rstrip('.').encode('idna').decode()
        if scoped and self.spec.allowed_domains and not any(host==d or host.endswith('.'+d) for d in self.spec.allowed_domains):
            # Search is a read-only discovery capability, never a mutation destination.
            if host not in {'www.google.com','www.bing.com','duckduckgo.com','html.duckduckgo.com','www.duckduckgo.com'}:
                raise PolicyError('The URL is outside the task domain scope.')
        try:
            addresses=await asyncio.get_running_loop().getaddrinfo(host,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise PolicyError('The destination could not be resolved.') from exc
        ips=sorted({row[4][0] for row in addresses},key=lambda ip:(ipaddress.ip_address(ip).version,ip))
        if not ips:
            raise PolicyError('No destination address.')
        if origin(url) not in self.private_origins and any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise PolicyError('Private, loopback, link-local, and reserved destinations are blocked.')
        return ips, p.port or (443 if p.scheme=='https' else 80)

    async def allows(self,url,scoped=True):
        try:
            await self.resolve(url,scoped)
            return True
        except (PolicyError, ValueError):
            return False

    def require_action(self, action, approved=False):
        if __import__('time').monotonic()-self.created > self.spec.duration_minutes*60:
            raise PolicyError('Task authorization has expired.')
        read={'navigate','extract','inspect','screenshot','scroll','wait','back','forward','switch_tab','new_tab','close_tab','hover','finish','skip','retry','site_search_filters','site_play'}
        if self.spec.mode=='observe' and action.kind not in read:
            raise PolicyError('Observe mode permits only read-only navigation and extraction.')
        implicit={'inspect','screenshot','finish','retry','skip','site_search_filters','site_play'}
        if action.kind=='site_play' and not re.search(r'\b(play|run)\b',self.spec.goal,re.I):
            raise PolicyError('Explicit playback was not requested.')
        if action.kind not in implicit and action.kind not in self.spec.allowed_actions:
            raise PolicyError('The action is outside the explicitly allowed action scope.')
        if action.kind in {'click','double_click','download','upload','dialog'} and not approved:
            raise PolicyError('Potential website changes require an explicit action approval.')
        if action.requires_approval and not approved:
            raise PolicyError('This action requires explicit approval.')
        if action.kind=='press' and action.value not in {'Enter','Tab','Escape','ArrowDown','ArrowUp','PageDown','PageUp','Control+A'}:
            raise PolicyError('Unsupported keyboard shortcut.')
        if action.kind in {'type','clear','select','check'} and self.spec.mode not in {'assisted','authorized'}:
            raise PolicyError('Form preparation requires Assisted or Authorized mode.')

SENSITIVE_ACTION = re.compile(r'(?i)\b(?:buy|purchase|pay|checkout|send|post|publish|delete|remove|erase|save|submit|accept|agree|permissions?|settings|subscribe|unsubscribe|transfer|confirm)\b')

class EgressProxy:
    """CONNECT tunnels connect to validated IPs, eliminating DNS check/use rebinding.

    The browser retains TLS certificate validation. No TLS interception, no sandbox bypass.
    Every connection is revalidated; all HTTP methods and navigation are also checked in
    BrowserController's route handler. No public listening socket.
    """
    def __init__(self,policy): self.policy=policy; self.server=None; self.connections=set()
    async def start(self):
        self.server=await asyncio.start_server(self.handle,'127.0.0.1',0,limit=65536)
        return f'http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}'
    async def handle(self,reader,writer):
        self.connections.add(writer)
        upstream=None
        try:
            head=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),15)
            line=head.split(b'\r\n',1)[0].decode('latin1')
            method,target,version=line.split(' ',2)
            url='https://'+target if method=='CONNECT' else target
            ips,port=await self.policy.resolve(url,scoped=False)
            last_error=None
            for ip in ips[:4]:
                try:
                    remote,upstream=await asyncio.wait_for(asyncio.open_connection(ip,port),4)
                    break
                except (OSError,asyncio.TimeoutError) as exc:last_error=exc
            if upstream is None:raise last_error or OSError('No reachable validated address.')
            self.connections.add(upstream)
            if method=='CONNECT':
                writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
            else:
                p=urlsplit(url)
                path=p.path or '/'
                if p.query:path+='?'+p.query
                headers=head.split(b'\r\n')[1:]
                headers=[h for h in headers if not h.lower().startswith((b'proxy-',b'connection:'))]
                upstream.write(f'{method} {path} {version}\r\n'.encode()+b'\r\n'.join(headers))
                await upstream.drain()
            await writer.drain()
            async def relay(src,dest):
                try:
                    while data:=await src.read(65536):
                        dest.write(data)
                        await dest.drain()
                finally:
                    dest.close()
            await asyncio.gather(relay(reader,upstream),relay(remote,writer))
        except (Exception, asyncio.CancelledError):
            try:writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n');await writer.drain()
            except Exception:pass
        finally:
            for stream in (writer,upstream):
                if stream:
                    stream.close();self.connections.discard(stream)
    async def close(self):
        if self.server:self.server.close();await self.server.wait_closed()
        for writer in list(self.connections):writer.close()

class Vault:
    def __init__(self,root:Path):
        root.mkdir(parents=True,exist_ok=True)
        self.root=root.resolve()
        keyfile=root/'vault.key'
        if keyfile.exists():
            data=keyfile.read_bytes()
            key=self._dpapi(data,False) if os.name=='nt' else data
        else:
            key=Fernet.generate_key()
            keyfile.write_bytes(self._dpapi(key,True) if os.name=='nt' else key)
            if os.name!='nt':keyfile.chmod(0o600)
        self.cipher=Fernet(key)

    @staticmethod
    def _dpapi(data,encrypt):
        class BLOB(ctypes.Structure):
            _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_char))]
        buf=ctypes.create_string_buffer(data)
        incoming=BLOB(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_char)))
        outgoing=BLOB()
        func=ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
        if not func(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(outgoing)):
            raise ctypes.WinError()
        try:return ctypes.string_at(outgoing.pbData,outgoing.cbData)
        finally:ctypes.windll.kernel32.LocalFree(outgoing.pbData)

    def encrypt(self,obj):return self.cipher.encrypt(json.dumps(obj,ensure_ascii=False).encode()).decode()
    def decrypt(self,text):return json.loads(self.cipher.decrypt(text.encode()))
    def file(self,name,data=None):
        # All paths are application-generated IDs, never website paths or user filenames.
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+',name):raise PolicyError('Invalid artifact path.')
        path=self.root/name
        if data is not None:path.write_bytes(self.cipher.encrypt(data));return name
        return self.cipher.decrypt(path.read_bytes())
