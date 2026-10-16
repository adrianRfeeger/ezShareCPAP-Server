"""Admit upload bodies before Waitress spools them to disk."""
import hmac
import threading
import uuid
from flask import Request
from waitress.channel import HTTPChannel
from waitress.parser import HTTPRequestParser
from waitress.utilities import BadRequest, RequestEntityTooLarge
import storage

_leases={}
_lock=threading.Lock()

class CountedStream:
 def __init__(self,stream,lease):self.stream,self.lease=stream,lease
 def write(self,data):
  count=self.stream.write(data);self.stream.flush();self.lease.consume(count);return count
 def __getattr__(self,name):return getattr(self.stream,name)

class UploadRequest(Request):
 def _get_file_stream(self,*args,**kwargs):
  stream=super()._get_file_stream(*args,**kwargs)
  lease=request_lease(self)
  return CountedStream(stream,lease) if lease else stream

def request_lease(request):
 with _lock:return _leases.get(request.headers.get('X-Ezshare-Lease',''))

def upload_channel(root,auth_header,max_upload,reserve):
 class Parser(HTTPRequestParser):
  lease=None
  token=None
  def parse_header(self,header):
   super().parse_header(header)
   self.headers.pop('X_EZSHARE_LEASE',None)
   is_upload=self.path=='/import' and self.command=='POST'
   if self.chunked or self.content_length>(max_upload if is_upload else 4096):
    self.error=RequestEntityTooLarge('A supported Content-Length is required; request exceeds the limit')
   elif is_upload:
    if not hmac.compare_digest(self.headers.get('AUTHORIZATION',''),auth_header):
     self.error=BadRequest('Sign in before uploading')
    elif self.content_length<=0:self.error=BadRequest('Upload Content-Length is required')
    else:
     try:
      self.lease=storage.reserve_space(root,'HTTP upload',self.content_length*3,reserve).__enter__()
      self.token=uuid.uuid4().hex
      with _lock:_leases[self.token]=self.lease
      self.headers['X_EZSHARE_LEASE']=self.token
     except OSError:self.error=RequestEntityTooLarge('Not enough disk space for this upload')
   if self.error:self.completed=True;self.expect_continue=False
  def received(self,data):
   body=self.headers_finished
   consumed=super().received(data)
   if body and self.lease:
    try:self.lease.consume(consumed)
    except OSError:
     self.error=RequestEntityTooLarge('Storage reserve reached');self.completed=True
   return consumed
  def close(self):
   try:super().close()
   finally:
    if self.lease:
     self.lease.__exit__(None,None,None);self.lease=None
    if self.token:
     with _lock:_leases.pop(self.token,None)
 class Channel(HTTPChannel):parser_class=Parser
 return Channel
