"""WebAuthn business rules. Each public operation runs in one DB transaction."""
import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from webauthn import (generate_authentication_options, generate_registration_options,
                      options_to_json, verify_authentication_response, verify_registration_response)
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                     ResidentKeyRequirement, UserVerificationRequirement)

CHALLENGE_SECONDS = 180
SESSION_SECONDS = 43200


class AuthError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


def now(): return datetime.now(timezone.utc)
def digest(value): return hashlib.sha256(value.encode()).digest()
def encode(value): return base64.urlsafe_b64encode(bytes(value)).rstrip(b'=').decode()


def decode(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise AuthError(400, '잘못된 자격 증명입니다.')
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, TypeError):
        raise AuthError(400, '잘못된 자격 증명입니다.') from None


class AuthService:
    def __init__(self, store, rp_id, rp_name, origin):
        self.store, self.rp_id, self.rp_name, self.origin = store, rp_id, rp_name, origin

    def current_user(self, token, required=True):
        row = self.store.get_session(digest(token)) if token else None
        if row and not row['revoked_at'] and row['expires_at'] > now():
            user = self.store.get_user(row['user_id'])
            if user:
                return user
        if required:
            raise AuthError(401, '패스키로 로그인해 주세요.')
        return None

    def _new_flow(self, purpose, user_id=None, pending_user_id=None):
        token = secrets.token_urlsafe(32)
        row = dict(id=uuid4(), purpose=purpose, user_id=user_id, pending_user_id=pending_user_id,
                   challenge=secrets.token_bytes(32), flow_binding_hash=digest(token),
                   expires_at=now() + timedelta(seconds=CHALLENGE_SECONDS), consumed_at=None)
        self.store.put_challenge(row)
        return row, token

    def _flow(self, id, token, purpose):
        try: id = UUID(str(id))
        except (ValueError, TypeError): raise AuthError(400, '인증 요청이 올바르지 않습니다.') from None
        row = self.store.get_challenge(id)  # PostgreSQL: SELECT FOR UPDATE
        if (not row or row['purpose'] != purpose or row['consumed_at']
                or row['expires_at'] <= now() or not token
                or not hmac.compare_digest(bytes(row['flow_binding_hash']), digest(token))):
            raise AuthError(400, '만료되었거나 이미 사용한 인증 요청입니다. 다시 시작해 주세요.')
        return row

    def _session(self, user_id, previous_token=None):
        if previous_token: self.store.revoke_session(digest(previous_token))
        token = secrets.token_urlsafe(32)
        self.store.put_session(dict(user_id=user_id, token_hash=digest(token),
                                    expires_at=now() + timedelta(seconds=SESSION_SECONDS), revoked_at=None))
        return token

    def begin_registration(self, display_name, session_token):
        user = self.current_user(session_token, required=False)
        pending = None if user else uuid4()
        user_id = user['id'] if user else pending
        row, token = self._new_flow('registration', user['id'] if user else None, pending)
        keys = self.store.list_keys(user_id) if user else []
        options = generate_registration_options(
            rp_id=self.rp_id, rp_name=self.rp_name, user_id=user_id.bytes,
            user_name=display_name, user_display_name=display_name,
            challenge=bytes(row['challenge']),
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=bytes(k['credential_id'])) for k in keys])
        return dict(flow_id=row['id'], flow_token=token, options=json.loads(options_to_json(options)))

    def finish_registration(self, flow_id, flow_token, credential, name, provider_note,
                            display_name, session_token):
        flow = self._flow(flow_id, flow_token, 'registration')
        if flow['user_id']:
            user = self.current_user(session_token)
            if user['id'] != flow['user_id']: raise AuthError(403, '계정이 변경되었습니다. 다시 시작해 주세요.')
            self.store.get_user(user['id'], lock=True)
            user_id = user['id']
        else:
            user_id = flow['pending_user_id']
        try:
            verified = verify_registration_response(
                credential=credential, expected_challenge=bytes(flow['challenge']),
                expected_rp_id=self.rp_id, expected_origin=self.origin,
                require_user_verification=True)
        except Exception:
            raise AuthError(400, '패스키 등록 검증에 실패했습니다.') from None
        if self.store.get_key(verified.credential_id):
            raise AuthError(409, '이미 등록된 패스키입니다. 다른 인증기를 선택해 주세요.')
        if not flow['user_id']:
            self.store.put_user(dict(id=user_id, display_name=display_name))
            self.store.seed_items(user_id)
        transports = credential.get('response', {}).get('transports', [])
        if not isinstance(transports, list): transports = []
        transports = [v for v in transports if v in ('usb', 'nfc', 'ble', 'internal', 'hybrid', 'smart-card')]
        self.store.put_key(dict(id=uuid4(), user_id=user_id, credential_id=verified.credential_id,
                               public_key=verified.credential_public_key, sign_count=verified.sign_count,
                               name=name, provider_note=provider_note, transports=transports,
                               backed_up=verified.credential_backed_up,
                               created_at=now(), revoked_at=None))
        self.store.consume_challenge(flow['id'])
        return dict(session_token=self._session(user_id, session_token))

    def begin_login(self):
        row, token = self._new_flow('authentication')
        options = generate_authentication_options(
            rp_id=self.rp_id, challenge=bytes(row['challenge']),
            user_verification=UserVerificationRequirement.REQUIRED)
        return dict(flow_id=row['id'], flow_token=token, options=json.loads(options_to_json(options)))

    def finish_login(self, flow_id, flow_token, credential, previous_token=None):
        flow = self._flow(flow_id, flow_token, 'authentication')
        credential_id = decode(credential.get('id'))
        key = self.store.get_key(credential_id)
        if not key or key['revoked_at']: raise AuthError(401, '사용할 수 없는 패스키입니다.')
        self.store.get_user(key['user_id'], lock=True)
        key = self.store.get_key(credential_id)  # Recheck after acquiring user lock.
        if not key or key['revoked_at']: raise AuthError(401, '사용할 수 없는 패스키입니다.')
        handle = credential.get('response', {}).get('userHandle')
        if not handle or decode(handle) != key['user_id'].bytes:
            raise AuthError(401, '패스키의 사용자 정보가 일치하지 않습니다.')
        try:
            verified = verify_authentication_response(
                credential=credential, expected_challenge=bytes(flow['challenge']),
                expected_rp_id=self.rp_id, expected_origin=self.origin,
                credential_public_key=bytes(key['public_key']),
                credential_current_sign_count=key['sign_count'], require_user_verification=True)
        except Exception:
            raise AuthError(401, '패스키 서명 검증에 실패했습니다.') from None
        self.store.update_key(credential_id, verified.new_sign_count, verified.credential_backed_up)
        self.store.consume_challenge(flow['id'])
        return dict(session_token=self._session(key['user_id'], previous_token))

    def logout(self, token):
        if token: self.store.revoke_session(digest(token))

    def keys(self, token):
        user = self.current_user(token)
        return [dict(id=str(k['id']), credential_id=encode(k['credential_id']), name=k['name'],
                     provider_note=k['provider_note'], created_at=k['created_at'])
                for k in self.store.list_keys(user['id'])]

    def delete_key(self, token, key_id):
        user = self.current_user(token)
        self.store.get_user(user['id'], lock=True)
        keys = self.store.list_keys(user['id'])
        target = next((k for k in keys if str(k['id']) == str(key_id)), None)
        if not target: raise AuthError(403, '본인의 활성 패스키만 삭제할 수 있습니다.')
        if len(keys) <= 1: raise AuthError(409, '마지막 패스키는 삭제할 수 없습니다. 먼저 새 패스키를 등록해 주세요.')
        self.store.revoke_key(target['id'], user['id'])

    def items(self, token):
        return self.store.list_items(self.current_user(token)['id'])

    def item(self, token, item_id):
        user = self.current_user(token)
        item = self.store.get_item(item_id)
        if not item or item['user_id'] != user['id']: raise AuthError(403, '본인 기록만 볼 수 있습니다.')
        return {k: v for k, v in item.items() if k != 'user_id'}
