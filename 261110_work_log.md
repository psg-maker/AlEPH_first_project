## 261110 work_log

aleph 8번 과제 시행 중(1번 과제 Develop)
주어진 가이드라인을 준수하여 설계함.

``` 
임의 값 설정 항목
- 재밌게 읽었던 책
- 좋아하는 스포츠
- 좋아하는 사람의 유형
```

supabase + FastAPI를 사용하려고 했으나, 
supabase 무료 플랜에서 제공하는 프로젝트 한도가 차서 Neon PostgreSQL을 채택, 배포는 Vercel에서 하기로 정함

Neon DB New project로 DATABASE_URL 을 .env.local에 변수 선언함
이후 Neon DB에 mermaid를 참조하여 erd를 생성하고, 기본 테이블 생성함.

### Neon DB base Table
```
| table_name | 용도 |
|---|---|
| challenges | 일회용 인증 요청 |
| passkeys | 등록된 패스키 공개키·정보 |
| private_items | 비공개 기록 |
| sessions | 로그인 상태 |
| users | 사용자 |
```

* 평소 FastAPI 테스팅은 해봤지만 실행은 따로 안해봤던 것 같아서 터미널에서 직접 실행하고 남김

### FastAPI 환경구축 터미널 실행 명령어(Bash 기준)

```
python -m venv .venv
source .venv/Scripts/activate
python -m pip install fastapi uvicorn "psycopg[binary]" python-dotenv
python -m pip freeze > requirements.txt
python -m uvicorn main:app --reload
```

### 명령어 세부의미

```
| 도구 | 역할 |
|---|---|
| FastAPI | URL별 요청 처리 |
| Uvicorn | FastAPI 서버 실행 |
| Psycopg | Python에서 PostgreSQL 연결·SQL 실행 |
| python-dotenv | `.env.local`의 환경변수 읽기 |

| main:app | main.py의 app을 실행하라는 뜻(@app)
| --reload | Python 코드 수정 -> 서버를 자동으로 다시 불러오는 옵션
```

### Python 환경 및 패키지 설치 확인

- 증상: FastAPI 서버는 실행됐지만, VS Code에서 import에 노란 밑줄이 표시됨.
- 추가 확인: 새 터미널에서 `ModuleNotFoundError: No module named 'psycopg'` 발생.
- 판단: 터미널과 VS Code가 사용하는 Python 환경이 다를 가능성이 있어 환경을 맞추기로 함.

#### 1. 필요한 패키지 설치

```
python -m pip install fastapi uvicorn "psycopg[binary]" python-dotenv

| python -m pip | 현재 선택된 Python의 pip를 실행한다.
| install | 뒤에 나열된 패키지를 설치한다.
| fastapi | API 요청을 처리하는 웹 프레임워크.
| uvicorn | FastAPI 애플리케이션을 실행하는 서버.
| "psycopg[binary]" | PostgreSQL 연결 드라이버와 사전 빌드된 바이너리를 설치한다.
| python-dotenv | `.env.local` 같은 파일의 환경변수를 읽는 도구.
```

#### 2. 패키지와 Python 경로 확인

```
python -c "import sys, psycopg, dotenv, fastapi; print(sys.executable)"

| python -c "..." | 따옴표 안의 Python 코드를 바로 실행한다.
| import sys, psycopg, dotenv, fastapi | 모듈을 불러와 현재 환경에서 사용 가능한지 확인한다.
| `;` | 한 줄에서 Python 문장을 구분한다.
| print(sys.executable) | 현재 실행 중인 Python 실행 파일의 전체 경로를 출력한다.
```

- 확인 기준: import 오류 없이 `.venv` 내부의 Python 경로가 출력되는지 확인한다.

#### 3. VS Code 환경 맞추기

```
Ctrl + Shift + P → Python: Select Interpreter
```

- 위에서 출력된 Python 경로를 선택해 편집기와 터미널의 환경을 맞춘다.


#### 환경설정에서 배운 점과 결과

- 해결 결과: 필요한 패키지를 설치하고 VS Code 인터프리터를 해당 가상환경으로 맞춘 뒤 import 경고가 사라졌다.
- 배운 점: Python 버전이 같아도 가상환경마다 설치된 패키지는 다르며, 터미널과 편집기가 같은 환경을 사용하는지 확인해야 한다.

환경을 맞췄으니 다음 챕터인 패스키 등록, 로그인으로 넘어간다.

### 패키지 설치 및 배포용 파일에 기록하는 과정

```
source .venv/Scripts/activate
python -m pip install webauthn
python -m pip freeze > requirements.txt
```

```
| 명령 | 하는 일 |
|---|---|
| `source .../activate` | 프로젝트의 가상환경 활성화 |
| `pip install webauthn` | 패스키 등록·로그인 응답을 검증할 라이브러리 설치 |
| `pip freeze > requirements.txt` | 설치된 패키지 버전을 배포용 파일에 기록 |
```

### .env.local에 개발용 설정 추가

```
WEBAUTHN_RP_ID=localhost
WEBAUTHN_RP_NAME=ALEPH Personal Records
WEBAUTHN_ORIGIN=http://localhost:8000
```

*RP ID: 패스키가 속하는 사이트의 도메인.
*RP NAME: 등록 창에 표시할 서비스 이름.
*ORIGIN: 서버가 인증 요청의 출처로 허용할 정확한 주소.

### codex가 만들어준 패스키 복붙 작업

```
python ~/Downloads/aleph8_passkeys/APPLY.py . --check
python ~/Downloads/aleph8_passkeys/APPLY.py .
python -m pip install -r requirements.txt
python -m unittest discover -v
python -m uvicorn main:app --reload
```

### Vercel 배포 및 패스키 설정에서 배운 점

- 첫 배포는 main 브랜치를 가져왔고, 해당 브랜치에는 FastAPI 실행 파일이 없어 FASTAPI_ENTRYPOINT_NOT_FOUND 오류가 발생했다.
- 에러코드를 읽어보니 main branch인 1번째 과제 branch를 읽고 있어 FastAPI 실행파일을 읽지 못한 것을 확인했다
- 배포 대상을 aleph_eight_project로 변경하면서 Branch Tracking도 반영되는 것을 확인했다.
- Root Directory는 저장소 내부 폴더 위치이며, Git 브랜치 이름과는 별개의 설정이다.
- 로컬 .env.local의 환경변수는 Vercel에 별도로 등록해야 한다.
- 환경변수 변경 후에는 재배포해야 적용된다.
- 패스키의 RP ID에는 도메인만, ORIGIN에는 https://를 포함한 정확한 사이트 주소를 설정했다.

첫 패스키 생성하면서 로그인이 되어야하는데 되지 않았었다.
구글 계정 확인 단계에서 휴대폰 인증 후 재시도하니 PC PIN 인증 후, 패스키 등록이 되었었음.

### 남은 것
- 학원 PC에서 두번째 패스키를 만들고 남은 검증 사항 확인 절차를 진행할 것.