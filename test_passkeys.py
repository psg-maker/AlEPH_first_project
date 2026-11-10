"""Offline security regression tests; cryptographic WebAuthn responses are real.

Only the external PostgreSQL storage is replaced by an in-memory transaction store.
Run: python -m unittest -v test_passkeys
"""
import base64
import copy
import hashlib
import json
import secrets
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

try:
    from passkey_service import AuthService, AuthError
except ImportError:
    AuthService = AuthError = None


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Authenticator:
    def __init__(self):
        self.secret = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(32)
        public = self.secret.public_key().public_numbers()
        self.cose = cbor2.dumps({1: 2, 3: -7, -1: 1,
                                -2: public.x.to_bytes(32, 'big'),
                                -3: public.y.to_bytes(32, 'big')})

    def registration(self, options, origin='http://localhost:8000'):
        self.handle = options['user']['id']
        client = json.dumps({'type': 'webauthn.create',
                             'challenge': options['challenge'], 'origin': origin}).encode()
        data = hashlib.sha256(b'localhost').digest() + b'\x45' + (0).to_bytes(4, 'big')
        data += bytes(16) + len(self.id).to_bytes(2, 'big') + self.id + self.cose
        att = cbor2.dumps({'fmt': 'none', 'attStmt': {}, 'authData': data})
        return {'id': b64(self.id), 'rawId': b64(self.id), 'type': 'public-key',
                'response': {'clientDataJSON': b64(client), 'attestationObject': b64(att),
                             'transports': ['internal']}, 'clientExtensionResults': {}}

    def authentication(self, options, bad_signature=False, origin='http://localhost:8000'):
        client = json.dumps({'type': 'webauthn.get',
                             'challenge': options['challenge'], 'origin': origin}).encode()
        data = hashlib.sha256(b'localhost').digest() + b'\x05' + (0).to_bytes(4, 'big')
        signature = self.secret.sign(data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        if bad_signature:
            signature = signature[:-1] + bytes([signature[-1] ^ 1])
        return {'id': b64(self.id), 'rawId': b64(self.id), 'type': 'public-key',
                'response': {'clientDataJSON': b64(client), 'authenticatorData': b64(data),
                             'signature': b64(signature), 'userHandle': self.handle},
                'clientExtensionResults': {}}


class MemoryStore:
    """Matches storage side effects, including rollback; not a signature-verifier mock."""
    def __init__(self):
        self.users = {}; self.credentials = {}; self.challenges = {}; self.sessions = {}; self.records = {}

    @contextmanager
    def transaction(self):
        snapshot = copy.deepcopy(self.__dict__)
        try:
            yield self
        except Exception:
            self.__dict__ = snapshot
            raise

    def put_challenge(self, row): self.challenges[row['id']] = row
    def get_challenge(self, id): return self.challenges.get(id)
    def consume_challenge(self, id): self.challenges[id]['consumed_at'] = datetime.now(timezone.utc)
    def get_session(self, token_hash): return self.sessions.get(token_hash)
    def put_session(self, row): self.sessions[row['token_hash']] = row
    def revoke_session(self, token_hash):
        if token_hash in self.sessions: self.sessions[token_hash]['revoked_at'] = datetime.now(timezone.utc)
    def get_user(self, id, lock=False): return self.users.get(id)
    def put_user(self, row): self.users[row['id']] = row
    def list_keys(self, user_id):
        return [r for r in self.credentials.values() if r['user_id'] == user_id and not r.get('revoked_at')]
    def get_key(self, credential_id): return self.credentials.get(credential_id)
    def put_key(self, row): self.credentials[row['credential_id']] = row
    def update_key(self, credential_id, count, backed_up):
        self.credentials[credential_id].update(sign_count=count, backed_up=backed_up)
    def revoke_key(self, id, user_id):
        for row in self.list_keys(user_id):
            if row['id'] == id: row['revoked_at'] = datetime.now(timezone.utc)
    def seed_items(self, user_id):
        self.records[user_id] = [{'id': str(user_id) + '-record', 'title': '가상 기록', 'body': '예시'}] * 3
    def list_items(self, user_id): return self.records.get(user_id, [])
    def get_item(self, id):
        for owner, rows in self.records.items():
            for row in rows:
                if row['id'] == id: return dict(row, user_id=owner)


class PasskeyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(AuthService, 'Passkey implementation is missing')
        self.store = MemoryStore()

    def call(self, method, *args, **kwargs):
        with self.store.transaction() as tx:
            return getattr(AuthService(tx, 'localhost', 'ALEPH', 'http://localhost:8000'), method)(*args, **kwargs)

    def register(self, session=None):
        authenticator = Authenticator()
        start = self.call('begin_registration', '테스트 사용자', session)
        end = self.call('finish_registration', start['flow_id'], start['flow_token'],
                        authenticator.registration(start['options']), '패스키', '테스트 인증기',
                        '테스트 사용자', session)
        return authenticator, end['session_token']

    def test_registration_saves_public_key_and_three_records(self):
        key, token = self.register()
        user = self.call('current_user', token)
        self.assertEqual(len(self.call('items', token)), 3)
        self.assertEqual(self.store.get_key(key.id)['user_id'], user['id'])
        self.assertNotIn('private_key', self.store.get_key(key.id))

    def test_cancelled_registration_creates_no_user_or_passkey(self):
        self.call('begin_registration', '취소', None)
        self.assertEqual(len(self.store.users), 0)
        self.assertEqual(len(self.store.credentials), 0)

    def test_invalid_origin_cannot_register_user(self):
        key = Authenticator(); start = self.call('begin_registration', 'A', None)
        with self.assertRaises(AuthError):
            self.call('finish_registration', start['flow_id'], start['flow_token'],
                      key.registration(start['options'], 'https://evil.example'), 'K', '', 'A', None)
        self.assertEqual(len(self.store.users), 0)

    def test_login_signature_is_verified_and_challenge_cannot_be_replayed(self):
        key, _ = self.register(); start = self.call('begin_login')
        credential = key.authentication(start['options'])
        result = self.call('finish_login', start['flow_id'], start['flow_token'], credential)
        self.assertTrue(self.call('current_user', result['session_token']))
        with self.assertRaises(AuthError):
            self.call('finish_login', start['flow_id'], start['flow_token'], credential)

    def test_modified_signature_does_not_create_session(self):
        key, _ = self.register(); start = self.call('begin_login')
        count = len(self.store.sessions)
        with self.assertRaises(AuthError):
            self.call('finish_login', start['flow_id'], start['flow_token'],
                      key.authentication(start['options'], bad_signature=True))
        self.assertEqual(len(self.store.sessions), count)

    def test_wrong_browser_flow_token_is_rejected(self):
        key, _ = self.register(); start = self.call('begin_login')
        with self.assertRaises(AuthError):
            self.call('finish_login', start['flow_id'], 'another-browser', key.authentication(start['options']))

    def test_expired_challenge_is_rejected(self):
        key, _ = self.register(); start = self.call('begin_login')
        self.store.challenges[start['flow_id']]['expires_at'] = datetime.now(timezone.utc) - timedelta(seconds=1)
        with self.assertRaises(AuthError):
            self.call('finish_login', start['flow_id'], start['flow_token'], key.authentication(start['options']))

    def test_logout_invalidates_existing_session_token(self):
        _, token = self.register(); self.call('logout', token)
        with self.assertRaises(AuthError): self.call('current_user', token)

    def test_another_user_cannot_read_records_or_delete_keys(self):
        _, a = self.register(); _, b = self.register()
        record = self.call('items', b)[0]
        other_key = self.call('keys', b)[0]
        with self.assertRaises(AuthError) as result: self.call('item', a, record['id'])
        self.assertEqual(result.exception.status, 403)
        with self.assertRaises(AuthError): self.call('delete_key', a, other_key['id'])
        self.assertEqual(len(self.call('keys', b)), 1)

    def test_deleted_key_cannot_login_and_remaining_key_can(self):
        first, token = self.register(); second, token = self.register(token)
        keys = self.call('keys', token); self.assertEqual(len(keys), 2)
        first_row = next(r for r in keys if r['credential_id'] == b64(first.id))
        self.call('delete_key', token, first_row['id'])
        start = self.call('begin_login')
        with self.assertRaises(AuthError):
            self.call('finish_login', start['flow_id'], start['flow_token'], first.authentication(start['options']))
        start = self.call('begin_login')
        result = self.call('finish_login', start['flow_id'], start['flow_token'], second.authentication(start['options']))
        self.assertTrue(self.call('current_user', result['session_token']))

    def test_last_key_deletion_is_blocked(self):
        _, token = self.register(); row = self.call('keys', token)[0]
        with self.assertRaises(AuthError) as result: self.call('delete_key', token, row['id'])
        self.assertEqual(result.exception.status, 409)

    def test_another_accounts_session_cannot_finish_additional_registration(self):
        _, a = self.register(); _, b = self.register()
        key = Authenticator(); start = self.call('begin_registration', 'A', a)
        with self.assertRaises(AuthError) as result:
            self.call('finish_registration', start['flow_id'], start['flow_token'],
                      key.registration(start['options']), 'K', '', 'A', b)
        self.assertEqual(result.exception.status, 403)

    def test_registration_challenge_cannot_be_used_twice(self):
        key = Authenticator(); start = self.call('begin_registration', 'A', None)
        args = (start['flow_id'], start['flow_token'], key.registration(start['options']), 'K', '', 'A', None)
        self.call('finish_registration', *args)
        with self.assertRaises(AuthError): self.call('finish_registration', *args)
        self.assertEqual(len(self.store.users), 1)

    def test_login_rejects_a_different_user_handle(self):
        key, _ = self.register(); start = self.call('begin_login')
        key.handle = b64(bytes(16))
        with self.assertRaises(AuthError):
            self.call('finish_login', start['flow_id'], start['flow_token'], key.authentication(start['options']))


if __name__ == '__main__': unittest.main()
