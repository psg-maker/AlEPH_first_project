import asyncio
import importlib
import json
import os
import unittest
from unittest.mock import patch

from test_passkeys import Authenticator, MemoryStore

try:
    import main
except ImportError:
    main = None


async def request(app, path, method='GET', body=None, origin=None, cookie=None):
    payload = json.dumps(body or {}).encode()
    headers = [(b'host', b'localhost:8000'), (b'content-type', b'application/json')]
    if origin: headers.append((b'origin', origin.encode()))
    if cookie: headers.append((b'cookie', cookie.encode()))
    scope = dict(type='http', asgi={'version': '3.0'}, http_version='1.1', method=method,
                 scheme='http', path=path, raw_path=path.encode(), query_string=b'',
                 root_path='', headers=headers, server=('localhost', 8000), client=('127.0.0.1', 1))
    sent = []; delivered = False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {'type': 'http.request', 'body': payload, 'more_body': False}
        await asyncio.Event().wait()
    async def send(message): sent.append(message)
    await app(scope, receive, send)
    start = next(m for m in sent if m['type'] == 'http.response.start')
    data = b''.join(m.get('body', b'') for m in sent if m['type'] == 'http.response.body')
    return start['status'], start['headers'], data


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(main, 'FastAPI passkey routes are missing')
        self.store = MemoryStore()
        self.factory = patch.object(main, 'transaction', self.store.transaction)
        self.factory.start(); self.addCleanup(self.factory.stop)

    def call(self, path, **kwargs): return asyncio.run(request(main.app, path, **kwargs))

    def test_private_data_without_session_is_401_and_not_cacheable(self):
        status, headers, body = self.call('/api/private/items')
        self.assertEqual(status, 401)
        self.assertIn((b'cache-control', b'no-store'), headers)

    def test_cross_site_registration_is_rejected_before_database_write(self):
        status, _, _ = self.call('/api/passkeys/register/options', method='POST',
                                  body={'display_name': 'A'}, origin='https://evil.example')
        self.assertEqual(status, 403)
        self.assertEqual(len(self.store.challenges), 0)

    def test_registration_options_bind_flow_with_httponly_cookie(self):
        status, headers, body = self.call('/api/passkeys/register/options', method='POST',
                                          body={'display_name': 'A'}, origin='http://localhost:8000')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertNotIn('flow_token', data)
        cookies = [v.decode() for k, v in headers if k == b'set-cookie']
        self.assertTrue(any('HttpOnly' in c and 'SameSite=strict' in c for c in cookies))

    def test_no_env_or_source_directory_is_served_as_static(self):
        for path in ('/.env.local', '/passkey_store.py', '/requirements.txt'):
            with self.subTest(path=path): self.assertEqual(self.call(path)[0], 404)

    def test_registration_login_and_logout_through_http_routes(self):
        origin = 'http://localhost:8000'
        key = Authenticator()
        def cookies(headers):
            return '; '.join(v.decode().split(';', 1)[0] for k, v in headers if k == b'set-cookie')
        status, headers, body = self.call('/api/passkeys/register/options', method='POST',
                                          body={'display_name': 'A'}, origin=origin)
        start = json.loads(body)
        status, headers, body = self.call('/api/passkeys/register/verify', method='POST',
            body={'flow_id': start['flow_id'], 'credential': key.registration(start['options']),
                  'display_name': 'A', 'name': '집 PC', 'provider_note': '가상 인증기'},
            origin=origin, cookie=cookies(headers))
        self.assertEqual(status, 200, body)
        session = cookies(headers)
        status, _, body = self.call('/api/private/items', cookie=session)
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)['items']), 3)
        self.assertEqual(self.call('/api/logout', method='POST', origin=origin, cookie=session)[0], 200)
        self.assertEqual(self.call('/api/private/items', cookie=session)[0], 401)
        status, headers, body = self.call('/api/passkeys/login/options', method='POST', origin=origin)
        start = json.loads(body)
        status, _, body = self.call('/api/passkeys/login/verify', method='POST',
            body={'flow_id': start['flow_id'], 'credential': key.authentication(start['options'])},
            origin=origin, cookie=cookies(headers))
        self.assertEqual(status, 200, body)


if __name__ == '__main__': unittest.main()
