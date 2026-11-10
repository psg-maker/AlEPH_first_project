# ALEPH 8 패스키 구현 적용

## 현재 결과

- 기존 자기소개 화면에 같은 색상과 카드 모양의 비공개 영역을 추가했습니다.
- 첫 패스키 등록, 패스키 로그인, 추가 등록, 목록, 삭제, 로그아웃을 구현했습니다.
- 첫 등록이 성공할 때만 사용자와 패스키와 가상 기록 3개를 같은 트랜잭션으로 생성합니다.
- 개인키와 세션 토큰 원문을 DB에 저장하지 않습니다. 공개키와 세션 토큰의 SHA-256 해시를 저장합니다.
- 추가 등록은 현재 로그인한 계정에 연결합니다. 로그아웃 상태의 첫 등록은 새 계정을 만듭니다.
- WebAuthn의 사용자 확인을 필수로 요청하고 서버에서도 검사합니다.
- 챌린지는 3분 안에 한 번만 성공적으로 사용할 수 있고, 발급받은 브라우저의 HttpOnly 쿠키에 연결합니다.
- 세션은 12시간 유효합니다. 로그아웃은 서버 세션을 폐기합니다.
- API 변경 요청은 설정한 Origin에서만 허용합니다. 세션 쿠키는 HttpOnly, SameSite=Strict이며 HTTPS에서는 Secure입니다.
- 다른 계정의 기록과 패스키 삭제 요청을 거절합니다. 마지막 패스키는 삭제하지 못하게 했습니다.
- 삭제는 사이트의 등록을 폐기합니다. 인증기나 비밀번호 관리자에 저장된 항목 자체를 지우지는 않습니다.
- 기존 세션은 패스키 삭제만으로 모두 폐기하지 않습니다. 로그아웃 또는 세션 만료가 별도로 필요합니다.
- 공개 HTML 소스 다운로드 버튼은 GitHub 브랜치 링크로 변경해 비공개 DOM 다운로드를 방지했습니다.

## 적용

서버를 Ctrl+C로 중지합니다. 압축을 풀고 기존 프로젝트 터미널에서 실행합니다.

```bash
python /c/Users/lntin/Downloads/aleph8_passkeys/APPLY.py . --check
python /c/Users/lntin/Downloads/aleph8_passkeys/APPLY.py .
python -m pip install -r requirements.txt
python -m unittest discover -v
python -m uvicorn main:app --reload
```

압축을 푼 위치가 다르면 APPLY.py 경로를 바꿉니다. APPLY.py는 현재 브랜치가
aleph_eight_project인지 확인하고, 파일이 예상 원본과 다른 경우 적용 전에 중단합니다.
바뀌는 원본은 .aleph8-backup-날짜 폴더에 백업합니다. .env.local과 work_log는 수정하지 않습니다.

## 로컬 설정

`.env.local`에는 기존 DATABASE_URL과 다음 값이 필요합니다. 파일을 공유하거나 커밋하지 않습니다.

```dotenv
WEBAUTHN_RP_ID=localhost
WEBAUTHN_RP_NAME=ALEPH Personal Records
WEBAUTHN_ORIGIN=http://localhost:8000
```

http://localhost:8000 으로 접속합니다. 127.0.0.1 주소와 혼용하지 않습니다.
로컬 패스키는 배포 사이트용 패스키와 별개입니다. 실사용 등록은 최종 배포 주소에서 합니다.

## Vercel 배포

1. 검증한 변경만 aleph_eight_project 브랜치에 커밋하고 푸시합니다. .env.local은 제외합니다.
2. Vercel에서 기존 저장소를 새 프로젝트로 가져오고 Framework Preset은 FastAPI로 설정합니다.
3. Production Branch를 aleph_eight_project로 지정합니다. main의 기존 소개 페이지와 구분합니다.
4. 환경변수 DATABASE_URL을 Vercel에 직접 입력합니다. 파일을 올리는 방식으로 전달하지 않습니다.
5. 고정 운영 도메인을 확인하고 다음 값을 Production 환경변수에 설정한 뒤 재배포합니다.

```dotenv
WEBAUTHN_RP_ID=확정된프로젝트주소.vercel.app
WEBAUTHN_RP_NAME=ALEPH Personal Records
WEBAUTHN_ORIGIN=https://확정된프로젝트주소.vercel.app
```

RP ID에는 https:// 또는 경로를 넣지 않습니다. ORIGIN에는 https://를 포함하고 마지막 /는 생략합니다.
코드는 기본 localhost 설정인 채로 Vercel에 배포되면 인증 API를 503으로 닫습니다.
제출 주소는 시크릿 창에서 Vercel 로그인 없이 공개 소개를 볼 수 있어야 합니다.
운영 DB를 Preview 환경에 무조건 공유하지 말고, 실제 등록은 고정 Production 주소에서 합니다.

## 집과 학원에서 사용

첫 패스키를 Google 비밀번호 관리자 또는 휴대폰처럼 학원에서도 접근할 수 있는 곳에 저장합니다.
집 PC에만 묶인 패스키 하나만 등록하면 학원 PC의 기존 계정 로그인 수단이 없을 수 있습니다.
학원에서는 기존 패스키로 먼저 로그인한 뒤, 독립적인 두 번째 패스키를 추가합니다.
같은 패스키의 동기화는 두 번째 등록으로 세지 않습니다. 목록에 서로 다른 두 항목이 보여야 합니다.

## 실제 기기 검증

1. 고정 배포 주소에서 첫 패스키 등록 → 가상 기록 3개 확인.
2. 로그아웃 → 비공개 기록이 사라지는지 확인 → 다시 패스키 로그인.
3. 추가 패스키 등록 → 목록에 두 항목, 이름과 등록일 확인.
4. 첫 패스키 삭제 → 로그아웃 → 삭제한 것은 실패하고 남은 것으로 로그인 성공하는지 확인.
5. 다른 계정 B를 만들고 A의 로그인 상태에서 B의 기록 URL과 패스키 삭제를 요청해 403 확인. 반대 방향도 확인.
6. 사용한 챌린지와 인증 응답을 다시 보내 거절되는지 확인. 실제 쿠키·토큰은 제출 기록에서 가립니다.
7. 시크릿 창에서 공개 화면과 소스에 비공개 내용이 없고, 비공개 API가 401인지 확인.

## 자동 검증과 한계

합성 인증기가 실제 EC 키와 서명을 만들고 실제 webauthn 검증 함수를 통과하거나 거절되는지 검사했습니다.
HTTP API의 등록→로그아웃→로그인 흐름, Origin 차단, 쿠키 설정, 비공개 API 보호도 테스트했습니다.
자동 테스트 22개와 JavaScript 문법 검사가 통과했습니다. 적용 도구의 원본 백업·실패 복구도 검사했습니다.
외부 PostgreSQL 저장소는 메모리 트랜잭션 저장소로 대체했으므로 실 DB SQL·동시 요청은 별도 검증이 필요합니다.
실제 Windows Hello, Google 비밀번호 관리자, 휴대폰 UI 및 Vercel 빌드는 아직 검증하지 않았습니다.
자동 테스트는 브라우저의 실제 인증 창이나 기기 간 이동 가능성을 보증하지 않습니다.

현재 과제용 버전에는 계정 복구, 등록 요청 빈도 제한, 오래된 챌린지·세션 자동 정리가 없습니다.
이 내용은 '아직 못 막은 것'에 구체적으로 적을 수 있습니다. 운영 서비스 수준의 보안 완성 판정은 아닙니다.
사용자별 권한은 FastAPI가 검사합니다. DB에 사용자별 RLS를 구성했다고 주장하지 않습니다.
배포 전에는 아래 별도 서버 전용 DB 계정을 적용하고 연결을 다시 확인하는 것을 권장합니다.

## 서버 전용 DB 역할

기존 관리자 계정의 연결은 로컬 초기 확인에만 사용하고, 배포용으로는 별도 SQL 역할을 만듭니다.
Neon SQL Editor에서 비밀번호 자리에 본인이 생성한 긴 무작위 비밀번호를 직접 입력합니다.
이 비밀번호나 완성된 연결 문자열을 채팅 또는 GitHub에 올리지 않습니다.

```sql
CREATE ROLE aleph8_app LOGIN PASSWORD '여기에_본인이_생성한_긴_무작위_비밀번호';
GRANT CONNECT ON DATABASE neondb TO aleph8_app;
GRANT USAGE ON SCHEMA aleph8_private TO aleph8_app;
GRANT SELECT, INSERT ON aleph8_private.users TO aleph8_app;
GRANT SELECT, INSERT, UPDATE ON aleph8_private.passkeys TO aleph8_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON aleph8_private.challenges TO aleph8_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON aleph8_private.sessions TO aleph8_app;
GRANT SELECT, INSERT ON aleph8_private.private_items TO aleph8_app;
```

DB명이 neondb가 아니면 실제 DB명으로 바꿉니다. 이 역할에는 관리자 역할을 추가로 부여하지 않습니다.
Neon Connect에서 이 역할의 연결 문자열을 확인해 DATABASE_URL을 변경하고 재시작합니다.
Vercel에서는 Neon의 pooled 연결 문자열을 사용해 동시 DB 연결 수를 관리합니다.
별도 역할을 사용하는 /api/health/db의 table_count도 5인지 확인합니다.
