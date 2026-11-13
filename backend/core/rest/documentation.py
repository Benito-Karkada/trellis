from pathlib import Path
import uuid
from django.http import FileResponse
from ..models import Membership
from .auth import authenticate,APIError,error_response


def access(request):
 request.api_request_id=uuid.uuid4()
 if request.headers.get('Authorization'):authenticate(request);return
 if not request.user.is_authenticated or not Membership.objects.filter(user=request.user,active=True,role__in=['instructor','head_ta','ta']).exists():
  raise APIError(401,'authentication_required','Sign in with a staff account, or use an API bearer token, to read the API documentation.')


def document(request,name,mime):
 try:access(request)
 except APIError as exc:return error_response(request,exc)
 response=FileResponse((Path(__file__).parent/name).open('rb'),content_type=mime)
 response['Cache-Control']='no-store'
 if mime=='text/html':response['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
 return response


def openapi(request):return document(request,'openapi.json','application/json')
def guide(request):return document(request,'guide.html','text/html')
