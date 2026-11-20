"""Authenticated loopback RPC to an explicitly selected Chrome extension tab."""
import asyncio
import secrets
import time
from .security import PolicyError

class ChromeBridge:
    def __init__(self):
        self.socket=None;self.tab=None;self.pending={};self.pair_code='';self.pair_until=0;self.session_token=''

    def pairing(self):
        self.pair_code=secrets.token_urlsafe(24);self.pair_until=time.monotonic()+600
        return self.pair_code

    def authenticate(self,token):
        if self.session_token and secrets.compare_digest(token,self.session_token):return True
        if self.pair_code and time.monotonic()<self.pair_until and secrets.compare_digest(token,self.pair_code):
            self.session_token=secrets.token_urlsafe(32);self.pair_code='';return True
        return False

    def status(self):
        return {'connected':self.socket is not None,'tab':self.tab}

    async def request(self,operation,**data):
        if not self.socket:raise PolicyError('Connect the LiquidPilot Chrome extension and select a tab first.')
        ident=secrets.token_hex(12);future=asyncio.get_running_loop().create_future();self.pending[ident]=future
        try:
            await self.socket.send_json({'id':ident,'operation':operation,**data})
            return await asyncio.wait_for(future,25)
        finally:self.pending.pop(ident,None)

    def receive(self,message):
        if message.get('event')=='tab':self.tab=message.get('tab');return
        future=self.pending.get(message.get('id'))
        if future and not future.done():
            if message.get('error'):future.set_exception(PolicyError(str(message['error'])[:500]))
            else:future.set_result(message.get('result'))

    async def disconnected(self,socket):
        if self.socket is not socket:return
        self.socket=None;self.tab=None
        for future in list(self.pending.values()):
            if not future.done():future.set_exception(PolicyError('Chrome connector disconnected. No action will be replayed.'))

bridge=ChromeBridge()
