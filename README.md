# 2026_aiAgent_academy
# FirstListen (가칭)

## Takeout 가져오기 추가

`POST /api/v1/imports`로 ZIP/JSON을 업로드하면 YouTube Music 기록을 필터·검증한 뒤 배치 저장하고 신규·중복·제외·검토·오류 건수를 반환합니다. 작업 결과와 검토 항목 조회도 지원합니다. 기존 회원 인증·사용자별 RLS·곡별 조회를 재사용합니다. Takeout의 알 수 없는 청취 시간과 가수는 NULL로 저장합니다. [API·DB 설계와 검증 방법](docs/TAKEOUT_IMPORT.md)

변경 반영: `docker compose up --build -d` (기존 볼륨 유지). 별도 DB 테스트: `python scripts/test_postgres_isolated.py`.

Android에서 YouTube Music 청취 이력을 자동으로 기록하고, 자연어 질문을 SQL로 변환해 곡별 최초 기록일과 총 재생 시간을 조회하는 서비스입니다.

FastAPI 백엔드의 인증, 청취 이벤트 동기화, 개인 곡 목록·통계, 제한된 한국어 질문 조회를 구현했습니다. 질문 분류는 LLM Tool Calling을 사용합니다. Android 클라이언트는 미디어 세션 관찰, Room 저장, WorkManager 전송과 로그인·권한·상태 화면을 포함합니다. 실제 기기 수집 검증과 월간 리포트는 후속 범위입니다.

## Android 실행

Android Studio에서 `android/`를 열고 JDK 21, SDK Platform 36.1을 설정합니다. 앱에서 서버에 로그인한 후 알림 접근을 허용하고 청취 기록 수집을 켜면 됩니다. [설치·빌드·수집 규칙과 검증 방법](android/README.md)을 참고하세요.

## 백엔드 실행

Docker Compose로 PostgreSQL, DB 역할, 마이그레이션, API를 함께 실행합니다.

```bash
docker compose up --build -d
```

- API 문서: http://localhost:8000/docs
- OpenAPI 계약: [docs/openapi.json](docs/openapi.json)
- 상태 확인: `GET /health`, DB 연결 확인: `GET /ready`
- 종료: `docker compose down` (DB 볼륨은 보존됩니다.)
- Android 연결: Emulator는 `http://10.0.2.2:8000`을 사용합니다. 실기기는 API가 기본적으로 이 PC(127.0.0.1)에만 열려 있으므로 `API_BIND=0.0.0.0 docker compose up -d`로 띄운 뒤 같은 Wi-Fi에서 `http://<개발 PC IP>:8000`으로 접속합니다. 외부에 공개되므로 개발 중에만 사용하고 방화벽에서 8000 포트 허용이 필요할 수 있습니다.
- Windows에서 `docker/init-db.sh`가 CRLF로 체크아웃되면 DB 역할 생성이 `set: Illegal option -`로 실패합니다. `.gitattributes`가 `*.sh`를 LF로 고정하며, 이전에 실패한 볼륨은 `docker compose down -v`로 지운 뒤 다시 실행해야 초기화됩니다.

기본 비밀번호는 로컬 개발용입니다. 설정을 변경하려면 `.env.example`을 `.env`로 복사한 뒤 수정해 주세요. Compose는 세 DB 비밀번호를 사용하고, Python을 직접 실행할 때는 URL 설정도 사용합니다. 비밀번호의 URL 예약 문자는 URL에서 인코딩해야 합니다. DB 초기화 스크립트는 빈 볼륨에서 한 번 실행되므로 기존 볼륨의 비밀번호는 `.env` 변경만으로 바뀌지 않습니다.

Python 3.12 이상으로 직접 실행할 수도 있습니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
docker compose up -d --build db
alembic upgrade head
uvicorn app.main:app --reload
```

직접 실행한 서버도 기본은 이 PC에서만 접속됩니다. Android 실기기에서 접속하려면 `uvicorn app.main:app --reload --host 0.0.0.0`으로 실행해 주세요.

애플리케이션은 시작할 때 테이블과 실행 계정의 권한을 확인합니다. PostgreSQL이 준비되지 않았거나 실행 계정이 테이블 소유자·관리자이거나 RLS가 꺼져 있으면 시작을 거부합니다. SQLite는 단위 테스트용이며 서버 실행용으로 지원하지 않습니다.

## 구현된 API

| 메서드 | 경로 | 기능 |
| --- | --- | --- |
| POST | `/api/v1/members` | 이메일·비밀번호 회원가입 |
| POST | `/api/v1/auth/login` | 만료 시각이 있는 Bearer 토큰 발급 |
| POST | `/api/v1/auth/logout` | 현재 토큰 즉시 폐기 |
| GET | `/api/v1/members/me` | 로그인 회원 조회 |
| POST | `/api/v1/listens/sync` | 이벤트 1~100개 원자적 저장·갱신 |
| GET | `/api/v1/tracks?q=입춘&limit=20&offset=0` | 본인 곡명·아티스트 검색 및 페이지 조회 |
| GET | `/api/v1/tracks/{track_id}` | 본인 곡 상세 |
| GET | `/api/v1/tracks/{track_id}/stats` | 최초 기록 시각·총 관찰 시간·이벤트 수 |
| POST | `/api/v1/chat` | 본인 곡의 최초 기록일·총 재생 시간 질문 |

회원가입·로그인은 `{"email":"you@example.com","password":"10자 이상의 비밀번호"}`를 받습니다. 이후 요청은 `Authorization: Bearer <access_token>`을 사용합니다. 비밀번호는 salt를 포함한 PBKDF2 해시로, 토큰은 SHA-256 해시로만 저장합니다. 이메일은 대소문자를 구분하지 않으며 비밀번호 앞뒤 공백은 유지합니다.

### Android 동기화 계약

```json
{
  "events": [
    {
      "event_id": "3c473c97-0a37-4d64-99be-18574b1cec08",
      "track": {
        "title": "입춘",
        "artist": "한로로",
        "album": null,
        "external_id": "youtube-music-track-id"
      },
      "observed_at": "2026-11-06T15:00:00+09:00",
      "listened_ms": 31000
    }
  ]
}
```

- 기기에서 청취 세션마다 UUID `event_id`를 생성하고 Room에 영구 저장합니다. 재시도·시간 갱신에는 동일 UUID를, 반복 청취에는 새 UUID를 사용해야 합니다. 서버는 이벤트를 회원별로 구분합니다.
- `observed_at`은 세션의 최초 관찰 시각이며 타임존이 필수입니다. 누적 시간을 갱신해도 최초 시각을 유지해 주세요. 서버는 같은 이벤트의 가장 이른 시각과 가장 큰 누적 시간을 유지합니다. 오프라인 지연 도착도 집계에 반영됩니다.
- 30,000ms 미만은 `ignored_below_threshold`로 응답하며 저장·집계하지 않습니다. 이후 동일 UUID로 기준을 넘으면 저장합니다. 한 이벤트의 상한은 24시간이고 현재보다 5분 이상 미래인 관찰 시각은 거절합니다.
- 동일 이벤트를 다른 곡에 재사용하면 `409`이며 배치 전체를 롤백합니다. 입력 오류는 `422`입니다. 타 사용자·존재하지 않는 곡 접근은 동일하게 `404`입니다.
- 서버가 반환하는 `track_id`를 곡 상세·통계·챗봇에 사용합니다. 사용자 ID를 요청 본문으로 받지 않습니다.
- `external_id`가 있으면 회원별 YouTube Music ID로 곡을 구분합니다. 없으면 정규화한 곡명·가수·앨범 조합을 사용합니다. 메타데이터가 같은 다른 녹음은 구분할 수 없고, ID 유무가 바뀌면 별도 곡으로 생성될 수 있습니다. 최초 저장된 메타데이터를 유지합니다.
- 전송 실패나 `503`은 같은 이벤트로 재시도해도 중복 합산되지 않습니다. 배치 처리는 전부 성공하거나 전부 취소됩니다.

### 질문 조회의 현재 범위

응답 JSON은 요청 질문 `question`과 답변 `answer`를 맨 앞에 표시합니다. `status`, 곡 정보, 집계값 등 기존 상세 필드도 그대로 반환합니다.

```json
{"question":"이 노래 총 재생 시간이 얼마야?","track_id":"서버에서 받은 UUID"}
```

`{"question":"입춘 언제부터 들었어?"}`처럼 곡명만 보내도 됩니다. 제목이 일치하는 곡을 우선 찾고, 없으면 제목 부분 검색을 사용합니다. 여러 후보이면 `ambiguous`와 최대 20개 `candidates`를 반환하며 `track_id`를 선택하기 전에는 집계하지 않습니다. `이 노래`에 곡 ID가 없으면 `needs_track`, 기록이 없으면 `not_found`, 지원하지 않는 질문은 `unsupported`를 반환합니다. 선택한 타 사용자 곡 ID는 `404`입니다.

`PICKLE_API_KEY`가 설정되면 LangChain `ChatOpenAI(model="pickle-general", base_url="https://llm.pcl.kr/v1", temperature=0).bind_tools(...)`로 질문을 분류합니다. 질문은 두 경로로 나뉩니다.

- **곡별 최초 기록일·총 재생 시간**: LLM이 `get_first_listen`, `get_total_listen_time`, `get_listen_summary` 중 하나를 고르고 `title` 인자로 곡명만 추출합니다. 곡 찾기 후 서버 고정 SQL을 실행합니다.
- **자유 통계**(“이번 달 제일 많이 들은 곡”, “월별 청취 시간” 등): LLM이 `query_listening_stats`를 고르면 Text-to-SQL로 처리합니다. LLM이 SELECT를 작성하면 전용 검증기를 거쳐 실행하고, 검증·실행에 실패하면 오류를 알려 주고 최대 3번 다시 작성하게 합니다(self-healing). 결과는 `metric: "stats"`, 최대 50행의 `rows`로 반환하며, `_ms`로 끝나는 열은 응답 문장에서 시간으로 표시합니다. 3번 모두 실패하면 `unsupported`입니다. “오늘·이번 달” 같은 기준 시점은 항상 DB의 `now() AT TIME ZONE 'Asia/Seoul'`로 계산하며(`CURRENT_DATE`는 검증기에서 거절), 생성 SQL은 사용자에게 보이지 않고 서버 로그에 남습니다. `CHAT_DEBUG=true`일 때만 응답 `debug.sql_attempts`에 시도별 SQL·오류를 포함합니다(평가·개발 전용). 통계 답변 문장은 기본적으로 결과 모양(값 하나·곡 순위·시간 흐름·그 외)에 맞춘 템플릿으로 만듭니다. `CHAT_LLM_SUMMARY=true`(기본 false)이면 결과가 1행일 때만 표시용으로 형식을 맞춘 결과 값을 LLM에 보내 2문장 이내로 요약하고, 요약 속 숫자+단위가 모두 입력 값에 있고 한글 수 표현(“세 곡” 등)이 없을 때만 채택합니다. 여러 행(순위 등)은 곡·숫자 짝이 뒤바뀌는 오류를 검증할 수 없어 항상 템플릿을 씁니다. 하나라도 다르거나 호출이 실패하면 템플릿 문장을 씁니다. 이 옵션을 켜면 본인 조회 결과가 LLM에 전송됩니다. 기간·순위 표현이 있으면 LLM이 곡별 도구를 골라도 이 경로로 보냅니다(전체 기간 값을 잘못 답하지 않도록).

다른 사용자·수정·삭제 요청과 SQL 기호는 LLM 호출 전에 규칙으로 거절합니다. 이 규칙 검사는 질문에 들어 있는 본인 곡 제목(2글자 이상)을 지운 뒤에 하므로 “12월의 기적”, “오늘도”, “Raindrop” 같은 제목이 기간·차단 단어로 오인되지 않습니다(LLM에는 원래 질문을 보냅니다). 사용자가 정한 제목으로 이 필터를 피할 수는 있지만, 이것은 사용성 필터일 뿐이고 데이터 보호는 SQL 검증기·사용자 범위 강제·읽기 전용 계정·RLS가 맡으므로 다른 사용자의 기록이 노출되지는 않습니다. 키가 없거나 호출이 실패하면 규칙 기반 분류(“언제부터 들었어?”, “최초 기록일”, “얼마나 들었어?”, “총 재생 시간”, “몇 시간” 등)로 대체하며, 이때 자유 통계 질문은 `unsupported`입니다. 날짜 응답은 기본 `Asia/Seoul`, API 시각은 UTC, 시간 집계는 밀리초를 기준으로 합니다. 대화 문맥은 저장하지 않습니다.

고정 SQL 경로는 SQLGlot AST를 서버의 허용된 집계·인증 필터와 대조하고 서버 SQL만 실행합니다. Text-to-SQL 경로는 별도 검증기(`app/ai/api_use/query/stats_validator.py`)를 사용합니다. SELECT 하나만, `listen_events`·`tracks` 테이블만, 허용 목록의 문법·함수(집계, 날짜 절단·추출, CASE, 순위 등)만 통과시키고 CTE·UNION·INTO·잠금·파라미터·알 수 없는 함수(`set_config`, `pg_sleep` 등)는 거절합니다. 통과한 SQL도 모든 테이블을 서버가 확정한 사용자 ID로 한정한 서브쿼리로 바꿔 실행하므로, LLM이 사용자 조건을 빠뜨리거나 조작해도 본인 기록만 조회합니다. 읽기 전용 계정·트랜잭션, 강제 RLS, 트랜잭션 로컬 사용자 컨텍스트, 2초 쿼리 제한을 함께 적용합니다. [SQLAlchemy의 원자적 upsert](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert)와 [PostgreSQL RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)를 사용합니다.

인증 요청은 IP당 분당 10회, 질문은 사용자당 분당 20회로 제한합니다. `429`의 `Retry-After` 이후 다시 요청해 주세요. 현재 제한기는 프로세스 메모리를 사용하므로 다중 워커·다중 인스턴스 운영 전에는 공유 저장소 기반 제한기로 교체해야 합니다. 운영 배포 시 HTTPS와 신뢰할 프록시 설정이 필요합니다.

## 백엔드 검증

```bash
# SQLite 기반 빠른 테스트: PostgreSQL 전용 테스트는 건너뜁니다.
pytest -q

# 마이그레이션을 적용한 개발용 PostgreSQL에서 동일 API와 RLS 검증
TEST_DATABASE_URL=postgresql+psycopg://firstlisten_app:local-app-password@localhost:5432/firstlisten \
TEST_READ_DATABASE_URL=postgresql+psycopg://firstlisten_reader:local-reader-password@localhost:5432/firstlisten \
pytest -q

# 실행 중인 API에 인증·재전송·지연 도착·집계·사용자 격리·로그아웃 검증
postman collection lint postman/collections/firstlisten
postman collection run postman/collections/firstlisten --no-report-events

# FastAPI 변경 후 저장된 OpenAPI 계약 갱신
python scripts/export_openapi.py
```

### 챗봇 평가 (실제 LLM)

`evals/`는 실제 Pickle LLM을 호출해 30개 질문(곡별 지표·다른 표현·곡 확정·자유 통계·거절·공격성)을 채점합니다. 비용이 들어 기본 `pytest`에는 넣지 않고, 프롬프트나 검증기를 바꿨을 때 따로 실행합니다.

```bash
# .env: PICKLE_API_KEY=..., CHAT_REQUESTS_PER_MINUTE=200, CHAT_DEBUG=true
docker compose up --build -d
pip install -e '.[eval]'
python -m evals.run_eval --runs 3            # 일부만: --only stats,first-01
```

평가 회원 A·B를 매번 새로 만들고 API로 기록을 넣은 뒤(`evals/seed.py`), 질문마다 `/api/v1/chat`을 N번 호출합니다. 정답은 `evals/dataset.jsonl`의 기준 SQL을 읽기 전용 계정·RLS로 실행해 매번 계산합니다. 경로(status·metric), 값(열 이름 무시), 회원 B 데이터 유출 없음을 모두 만족해야 합격입니다. 응답 시간은 합격 판정과 분리해 평균과 10초 초과 건수로만 표시합니다(통계 질문은 LLM을 2~4번 부릅니다). 카테고리별 pass@1(평균 정확도)·pass^N(N번 모두 합격한 질문 비율)·평균 SQL 시도와 실패한 질문의 생성 SQL을 출력합니다. 결과는 `evals/results/<시각>.json`에 저장되므로 프롬프트 수정 전후를 비교할 수 있습니다. 채점기 자체는 `tests/test_evals.py`에서 검증합니다. 개발 DB에서만 실행해 주세요.

PostgreSQL 테스트와 Postman은 임의 이메일의 테스트 회원·기록을 생성하므로 개발 전용 DB에서 실행해 주세요. Postman은 기본 `http://127.0.0.1:8000`을 사용하며 다른 주소는 `--env-var base_url=http://...`으로 지정할 수 있습니다. CLI 없이 Postman 앱을 사용하려면 [OpenAPI 계약](docs/openapi.json)을 가져올 수 있습니다.

코드는 `app/`, 마이그레이션은 `migrations/`, 회귀 테스트는 `tests/`, 실행 가능한 Postman v3 컬렉션은 `postman/collections/firstlisten/`에 있습니다.

```
app/
├── main.py              # 진입점: 앱 생성, 시작 시 DB 권한 점검, 라우터 등록
├── config.py            # 환경변수 설정
├── database.py          # DB 엔진·세션, RLS 사용자 컨텍스트, 역할 점검
├── dependencies.py      # Depends 공통: 로그인 회원, DB 세션, 요청 제한
├── utils.py             # 문자열 정규화
├── models/              # DB 엔티티 (member: 회원·토큰 / track: 곡·청취 이벤트)
├── schemas/             # 요청·응답 DTO (member / listen / track / chat)
├── routers/             # API 라우팅 (system / member / listen / track / chat)
├── services/            # 비즈니스 로직 (auth, rate_limiter, listen·track·chat 서비스)
└── ai/api_use/          # 챗봇 AI 모듈
    ├── intent_list.py   # Tool Calling 도구 목록·분류 프롬프트
    ├── chat_classify.py # 범위 가드 → LLM 분류 → 정규식 fallback
    └── query/           # validator(SQL 검증) · executor(실행) · response(응답 문장)
```

## 기능

- **회원(member)**: 회원가입 / 로그인 / 본인 기록 접근 권한 확인
- **자동 기록(listen)**: Android 미디어 세션 관찰 / 청취 판정 / 오프라인 저장 / 서버 동기화
- **음악(track)**: 내 곡 목록 검색 / 곡별 최초 기록일 / 기록된 총 재생 시간 조회
- **챗봇(chat)**: 자연어 질문 → Text-to-SQL → 본인 청취 기록 조회 → 응답
- **리포트(report, 후속)**: 월간 디깅 지표 집계 / LLM 요약

## 기술 구성

- **Android**: Kotlin, Jetpack Compose, NotificationListenerService, MediaSessionManager, MediaController
- **기기 저장·동기화**: Room, WorkManager
- **백엔드**: FastAPI, Pydantic, SQLAlchemy, Alembic
- **데이터베이스**: PostgreSQL
- **자연어 조회**: LLM, Tool Calling, SQLGlot 기반 SQL 검증
- **테스트**: Postman API 테스트 / Android 실제 기기 테스트

## 기록 기준

- 초기 청취 인정 기준은 누적 30초 이상 관찰이며, 실제 기기 테스트 후 확정합니다.
- 최초 기록일은 인정된 청취 이벤트의 가장 이른 관찰 시각입니다. 설치 전이나 수집 중단 중의 청취는 보장하지 않습니다.
- 총 재생 시간은 인정된 이벤트에서 관찰한 시간의 합계입니다. 일시정지·버퍼링·확인 불가능한 구간과 30초 미만 재생은 제외합니다.
- 30초 이후에도 같은 이벤트의 누적 시간을 갱신합니다. 재전송 시 누적값을 더하지 않고 최댓값을 유지해 중복 집계를 방지합니다.
- YouTube Music이 제공하는 곡 정보와 재생 상태의 안정성은 실제 기기에서 검증합니다.

## 요청 분류 및 응답

- **최초 기록일 질문**
  - “이 노래 제 최초 기록이 언제야?”, “입춘 언제부터 들었어?”
  - 곡 확인 → `MIN(observed_at)`을 사용하는 SQL 생성 → 검증·실행
  - “이 앱의 기록에서는 2026년 11월 6일에 처음 확인되었습니다.”와 같이 응답합니다.

- **총 재생 시간 질문**
  - “이 노래 총 재생 시간이 얼마야?”, “입춘 얼마나 들었어?”
  - 곡 확인 → `SUM(listened_ms)`를 사용하는 SQL 생성 → 검증·실행
  - 서버가 밀리초를 시간·분으로 변환해 “기록된 총 재생 시간은 2시간 15분입니다.”와 같이 응답합니다.

- **곡이 불명확한 질문**
  - 곡 상세 화면의 “이 노래”는 선택된 곡 ID를 사용합니다.
  - 곡명만 제시하면 본인 보관함에서 검색합니다. 후보가 여러 개면 선택을 요청하고 실행을 보류합니다.

- **기록이 없는 질문**
  - “해당 곡의 청취 기록이 없습니다.”라고 응답합니다. 날짜나 시간을 추측하지 않습니다.

- **그 외 질문**
  - 다른 사용자 기록 조회, 데이터 변경, 지원 범위 밖의 질문은 조회하지 않고 지원 범위를 안내합니다.

## Text-to-SQL 및 Tool Calling

```text
사용자: “이 노래 총 재생 시간이 얼마야?”
  → 서버: 로그인 사용자와 곡 확인
  → LLM: 허용된 스키마와 지표 정의로 SQL 생성
  → Tool Calling: 검증된 조회를 실행하도록 서버에 요청
  → 서버: SQL 검증 및 인증 기반 파라미터 바인딩
  → PostgreSQL: 본인 기록 집계
  → 서버: 결과를 날짜·시간 형식으로 변환해 응답
```

SQL 예시:

```sql
SELECT
    MIN(observed_at) AS first_recorded_at,
    COALESCE(SUM(listened_ms::bigint), 0) AS total_listened_ms
FROM listen_events
WHERE user_id = :authenticated_user_id
  AND track_id = :resolved_track_id;
```

- 사용자 ID는 인증 정보에서, 곡 ID는 서버에서 확인한 값으로 바인딩합니다.
- SQLGlot으로 전체 구문을 검사하고 단일 SELECT, 허용된 테이블·컬럼·집계 함수·필터만 허용합니다. 지표별 계산식도 검증합니다.
- 초기에는 CTE, 서브쿼리, UNION, 임의 JOIN 및 데이터 변경 명령을 지원하지 않습니다.
- 전용 읽기 계정, 읽기 전용 트랜잭션, 사용자별 RLS를 적용합니다. RLS를 우회하는 소유자·관리자 권한은 사용하지 않습니다.
- 사용자 컨텍스트는 트랜잭션마다 서버가 설정하며, 커넥션 풀 재사용 시 다른 사용자에게 남지 않도록 합니다.
- 실행 시간과 요청 빈도를 제한합니다. LLM 출력은 검증 없이 실행하지 않습니다.
- LLM은 SQL을 제안하고 실제 날짜와 수치는 DB가 계산합니다. 초기 응답은 고정 문구로 구성할 수 있습니다.

## 구현 순서 및 검증

1. **백엔드 먼저 구현**: 데이터 모델 / 이벤트 저장·갱신 / 곡별 통계 API
2. **Postman 테스트**: 인증 / 중복 전송 / 지연 도착 / 사용자 간 접근 차단 / 집계 정확도
3. **Android 구현**: 권한 설정 / 자동 기록 / 로컬 저장 / 서버 동기화
4. **실제 기기 테스트**: 화면 잠금 / 일시정지 / 건너뛰기 / 반복 / 오프라인 / 재부팅
5. **Text-to-SQL 구현**: 질문 분류 / 곡 확인 / SQL 생성·검증 / 답변
6. **질문 테스트**: 표현이 달라도 같은 결과인지, 모호한 곡을 되묻는지, 비허용 SQL과 타 사용자 조회를 차단하는지 확인

같은 이벤트를 31초 → 120초 → 31초로 전송해도 이벤트는 한 개, 총 시간은 120초로 유지되어야 합니다. 자연어 조회 결과는 기준 SQL의 집계값과 비교합니다.

Android 수집기와 최소 권한·조회 화면은 `android/`에 구현되어 있습니다. 실제 기기에서 YouTube Music의 메타데이터·재생 상태 제공과 백그라운드 수집을 확인해야 합니다. 별도 웹 프론트엔드는 후순위로 둡니다.

3인 팀의 AI 에이전트 역할 분담, 공통 프롬프트, Android-백엔드 API 호출 계약은 [팀·AI 에이전트 호출 규약](docs/team-agent-contract.md)을 참고하세요.

## 고도화

- **대화 문맥**: 직전 대화에서 선택한 곡을 기억해 “그 노래 총 몇 시간 들었어?” 처리
- **조회 확장**: 기간별 청취, 가장 많이 들은 곡, 월별 신규 아티스트 조회
- **월간 리포트**: 서버가 계산한 지표를 LLM이 문장으로 요약
- **Vector 검색**: 개인 발견 메모가 추가되면 의미 기반 검색에 적용. 날짜·시간 집계에는 사용하지 않음
- **비용 최적화**: 질문 길이·호출 횟수 제한, 사용자·곡·질문 유형별 캐싱. 기록 갱신 시 캐시 무효화

## 중간 피드백

- 데이터 모델과 최초 기록일·총 재생 시간 기준 확정 후
- 실제 기기 자동 기록 시연 후
- 자연어 질문으로 본인 기록을 조회하는 시연 후
