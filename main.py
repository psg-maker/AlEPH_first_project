import logging
import os
from pathlib import Path
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from passkey_service import AuthError, AuthService, CHALLENGE_SECONDS, SESSION_SECONDS
from passkey_store import transaction

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env.local', override=False)
app = FastAPI()
logger = logging.getLogger('uvicorn.error')
SESSION_COOKIE = 'aleph8_session'
FLOW_COOKIE = 'aleph8_flow'


def settings():
    origin = os.getenv('WEBAUTHN_ORIGIN', 'http://localhost:8000').rstrip('/')
    rp_id = os.getenv('WEBAUTHN_RP_ID', 'localhost')
    if os.getenv('VERCEL') and (not origin.startswith('https://') or rp_id == 'localhost'):
        raise AuthError(503, '운영용 패스키 도메인을 설정해 주세요.')
    return rp_id, os.getenv('WEBAUTHN_RP_NAME', 'ALEPH Personal Records'), origin


def run(method, *args):
    config = settings()
    with transaction() as store:
        return getattr(AuthService(store, *config), method)(*args)


def cookie(response, name, token, max_age):
    response.set_cookie(name, token, max_age=max_age, httponly=True,
                        secure=settings()[2].startswith('https://'), samesite='strict', path='/')


def session_token(request): return request.cookies.get(SESSION_COOKIE)


@app.middleware('http')
async def request_boundary(request, call_next):
    try:
        if request.url.path.startswith('/api/') and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if request.headers.get('origin') != settings()[2]:
                raise AuthError(403, '허용되지 않은 요청 출처입니다.')
            if len(await request.body()) > 65536:
                raise AuthError(413, '요청이 너무 큽니다.')
        response = await call_next(request)
    except AuthError as error:
        response = JSONResponse({'detail': error.message}, status_code=error.status)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response


@app.exception_handler(AuthError)
async def auth_error(request, error):
    return JSONResponse({'detail': error.message}, status_code=error.status)


@app.exception_handler(psycopg.Error)
async def database_error(request, error):
    logger.error('Database request failed: %s', type(error).__name__)
    status = 409 if isinstance(error, psycopg.errors.UniqueViolation) else 503
    return JSONResponse({'detail': '이미 등록된 정보입니다. 다시 확인해 주세요.' if status == 409 else 'DB 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.'}, status_code=status)


class RegistrationStart(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator('display_name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('이름을 입력해 주세요.')
        return value.strip()


class CredentialInput(BaseModel):
    flow_id: UUID
    credential: dict

    @field_validator('credential')
    @classmethod
    def valid_shape(cls, value):
        if not isinstance(value.get('id'), str) or not isinstance(value.get('response'), dict):
            raise ValueError('자격 증명 형식이 올바르지 않습니다.')
        return value


class RegistrationFinish(CredentialInput, RegistrationStart):
    name: str = Field(min_length=1, max_length=100)
    provider_note: str = Field(default='', max_length=200)


def flow_response(result):
    token = result.pop('flow_token')
    result['flow_id'] = str(result['flow_id'])
    response = JSONResponse(result)
    cookie(response, FLOW_COOKIE, token, CHALLENGE_SECONDS)
    return response


def login_response(result):
    response = JSONResponse({'ok': True})
    cookie(response, SESSION_COOKIE, result['session_token'], SESSION_SECONDS)
    response.delete_cookie(FLOW_COOKIE, path='/')
    return response


@app.get('/')
def introduction(): return FileResponse(BASE_DIR / 'index.html')


@app.get('/passkeys.js', include_in_schema=False)
def passkeys_js(): return FileResponse(BASE_DIR / 'public' / 'passkeys.js', media_type='application/javascript')


@app.get('/passkeys.css', include_in_schema=False)
def passkeys_css(): return FileResponse(BASE_DIR / 'public' / 'passkeys.css', media_type='text/css')


@app.get('/api/health')
def health(): return {'server': 'ok'}


@app.get('/api/health/db')
def database_health():
    if os.getenv('VERCEL'): raise HTTPException(404, 'Not found')
    with transaction() as store:
        row = store.query('SELECT 1 AS result', one=True)
        tables = store.query("""SELECT count(*) AS count FROM information_schema.tables
            WHERE table_schema='aleph8_private' AND table_type='BASE TABLE'""", one=True)
    return {'database': 'ok', 'select_1': row['result'], 'table_count': tables['count']}


@app.get('/api/me')
def me(request: Request):
    user = run('current_user', session_token(request), False)
    return {'user': {'id': str(user['id']), 'display_name': user['display_name']} if user else None}


@app.post('/api/passkeys/register/options')
def registration_options(body: RegistrationStart, request: Request):
    return flow_response(run('begin_registration', body.display_name, session_token(request)))


@app.post('/api/passkeys/register/verify')
def registration_verify(body: RegistrationFinish, request: Request):
    return login_response(run('finish_registration', body.flow_id, request.cookies.get(FLOW_COOKIE),
                              body.credential, body.name, body.provider_note, body.display_name,
                              session_token(request)))


@app.post('/api/passkeys/login/options')
def login_options(): return flow_response(run('begin_login'))


@app.post('/api/passkeys/login/verify')
def login_verify(body: CredentialInput, request: Request):
    return login_response(run('finish_login', body.flow_id, request.cookies.get(FLOW_COOKIE),
                              body.credential, session_token(request)))


@app.post('/api/logout')
def logout(request: Request):
    run('logout', session_token(request))
    response = JSONResponse({'ok': True})
    response.delete_cookie(SESSION_COOKIE, path='/')
    response.delete_cookie(FLOW_COOKIE, path='/')
    return response


@app.get('/api/passkeys')
def passkeys(request: Request): return {'passkeys': run('keys', session_token(request))}


@app.delete('/api/passkeys/{key_id}')
def delete_key(key_id: UUID, request: Request):
    run('delete_key', session_token(request), key_id)
    return {'ok': True}


@app.get('/api/private/items')
def private_items(request: Request): return {'items': run('items', session_token(request))}


@app.get('/api/private/items/{item_id}')
def private_item(item_id: UUID, request: Request): return run('item', session_token(request), item_id)
