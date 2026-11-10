"""Parameterized PostgreSQL storage; DB transactions serialize challenge use and key deletion."""
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


@contextmanager
def transaction():
    url = os.getenv('DATABASE_URL')
    if not url:
        from passkey_service import AuthError
        raise AuthError(503, 'DATABASE_URL 설정을 확인해 주세요.')
    with psycopg.connect(url, sslmode='require', connect_timeout=10, row_factory=dict_row) as connection:
        connection.execute("SET LOCAL statement_timeout = '10s'")
        yield PostgresStore(connection)


class PostgresStore:
    def __init__(self, connection): self.connection = connection

    def query(self, sql, params=(), one=False):
        cursor = self.connection.execute(sql, params)
        if cursor.description:
            return cursor.fetchone() if one else cursor.fetchall()

    def put_challenge(self, row):
        self.query('''INSERT INTO aleph8_private.challenges
            (id, user_id, pending_user_id, purpose, challenge, flow_binding_hash, expires_at)
            VALUES (%(id)s, %(user_id)s, %(pending_user_id)s, %(purpose)s,
                    %(challenge)s, %(flow_binding_hash)s, %(expires_at)s)''', row)

    def get_challenge(self, id):
        return self.query('SELECT * FROM aleph8_private.challenges WHERE id=%s FOR UPDATE', (id,), one=True)

    def consume_challenge(self, id):
        self.query('UPDATE aleph8_private.challenges SET consumed_at=now() WHERE id=%s', (id,))

    def get_session(self, token_hash):
        return self.query('SELECT * FROM aleph8_private.sessions WHERE token_hash=%s', (token_hash,), one=True)

    def put_session(self, row):
        self.query('''INSERT INTO aleph8_private.sessions (user_id, token_hash, expires_at)
            VALUES (%(user_id)s, %(token_hash)s, %(expires_at)s)''', row)

    def revoke_session(self, token_hash):
        self.query('UPDATE aleph8_private.sessions SET revoked_at=now() WHERE token_hash=%s', (token_hash,))

    def get_user(self, id, lock=False):
        return self.query('SELECT * FROM aleph8_private.users WHERE id=%s' + (' FOR UPDATE' if lock else ''),
                          (id,), one=True)

    def put_user(self, row):
        self.query('INSERT INTO aleph8_private.users (id, display_name) VALUES (%(id)s, %(display_name)s)', row)

    def list_keys(self, user_id):
        return self.query('''SELECT * FROM aleph8_private.passkeys
            WHERE user_id=%s AND revoked_at IS NULL ORDER BY created_at, id''', (user_id,))

    def get_key(self, credential_id):
        return self.query('SELECT * FROM aleph8_private.passkeys WHERE credential_id=%s', (credential_id,), one=True)

    def put_key(self, row):
        self.query('''INSERT INTO aleph8_private.passkeys
            (id, user_id, credential_id, public_key, sign_count, name, provider_note, transports, backed_up)
            VALUES (%(id)s, %(user_id)s, %(credential_id)s, %(public_key)s, %(sign_count)s,
                    %(name)s, %(provider_note)s, %(transports)s, %(backed_up)s)''', row)

    def update_key(self, credential_id, count, backed_up):
        self.query('''UPDATE aleph8_private.passkeys SET sign_count=%s, backed_up=%s, last_used_at=now()
            WHERE credential_id=%s''', (count, backed_up, credential_id))

    def revoke_key(self, id, user_id):
        self.query('UPDATE aleph8_private.passkeys SET revoked_at=now() WHERE id=%s AND user_id=%s', (id, user_id))

    def seed_items(self, user_id):
        examples = [
            ('project', '개인 독서 기록 사이트', '과제용 가상 데이터: 책 목록 화면을 완성했고 검색 기능을 준비 중입니다.'),
            ('application', '별빛시스템즈 지원 계획', '과제용 가상 데이터: 11월 20일 지원 예정이며 프로젝트 설명을 정리 중입니다.'),
            ('reflection', '요구사항부터 정리하기', '과제용 가상 데이터: 기능부터 만들던 방식을 바꿔 요구사항을 먼저 정리했습니다.'),
        ]
        for category, title, body in examples:
            self.query('''INSERT INTO aleph8_private.private_items (user_id, category, title, body)
                VALUES (%s, %s, %s, %s)''', (user_id, category, title, body))

    def list_items(self, user_id):
        return self.query('''SELECT id, category, title, body, record_date
            FROM aleph8_private.private_items WHERE user_id=%s ORDER BY record_date DESC, created_at, id''', (user_id,))

    def get_item(self, id):
        return self.query('''SELECT id, user_id, category, title, body, record_date
            FROM aleph8_private.private_items WHERE id=%s''', (id,), one=True)
