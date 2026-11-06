# 2026_aiAgent_academy
# FirstListen (가칭)

Android에서 YouTube Music 청취 이력을 자동으로 기록하고, 자연어 질문을 SQL로 변환해 곡별 최초 기록일과 총 재생 시간을 조회하는 서비스입니다.

FastAPI 백엔드의 인증, 청취 이벤트 동기화, 개인 곡 목록·통계, 제한된 한국어 질문 조회를 구현했습니다. Android 수집기, 외부 LLM Tool Calling, 월간 리포트는 후속 구현 범위입니다.

## 백엔드 실행

Docker Compose로 PostgreSQL, DB 역할, 마이그레이션, API를 함께 실행합니다.

```bash
docker compose up --build -d
```

- API 문서: http://localhost:8000/docs
- OpenAPI 계약: [docs/openapi.json](docs/openapi.json)
- 상태 확인: `GET /health`, DB 연결 확인: `GET /ready`
- 종료: `docker compose down` (DB 볼륨은 보존됩니다.)

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

```json
{"question":"이 노래 총 재생 시간이 얼마야?","track_id":"서버에서 받은 UUID"}
```

`{"question":"입춘 언제부터 들었어?"}`처럼 곡명만 보내도 됩니다. 제목이 일치하는 곡을 우선 찾고, 없으면 제목 부분 검색을 사용합니다. 여러 후보이면 `ambiguous`와 최대 20개 `candidates`를 반환하며 `track_id`를 선택하기 전에는 집계하지 않습니다. `이 노래`에 곡 ID가 없으면 `needs_track`, 기록이 없으면 `not_found`, 지원하지 않는 질문은 `unsupported`를 반환합니다. 선택한 타 사용자 곡 ID는 `404`입니다.

현재 질문 분류·SQL 제안은 규칙 기반이며 외부 LLM 호출은 없습니다. 지원하는 한국어 표현에는 “언제부터 들었어?”, “최초 기록일”, “얼마나 들었어?”, “총 재생 시간”, “몇 시간”이 포함됩니다. 자유로운 모든 표현을 이해하는 챗봇은 아닙니다. 날짜 응답은 기본 `Asia/Seoul`, API 시각은 UTC, 시간 집계는 밀리초를 기준으로 합니다. 대화 문맥은 저장하지 않습니다.

SQLGlot AST를 서버의 허용된 집계·인증 필터와 대조하고 검증된 서버 SQL만 실행합니다. 이 검증기는 향후 LLM Tool Calling에도 재사용할 수 있습니다. 현재는 쿼리의 의미가 비슷해도 허용된 AST 형태가 아니면 거절하는 보수적인 정책입니다. 읽기 전용 계정·트랜잭션, 강제 RLS, 트랜잭션 로컬 사용자 컨텍스트, 2초 쿼리 제한을 함께 적용합니다. [SQLAlchemy의 원자적 upsert](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert)와 [PostgreSQL RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)를 사용합니다.

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

PostgreSQL 테스트와 Postman은 임의 이메일의 테스트 회원·기록을 생성하므로 개발 전용 DB에서 실행해 주세요. Postman은 기본 `http://127.0.0.1:8000`을 사용하며 다른 주소는 `--env-var base_url=http://...`으로 지정할 수 있습니다. CLI 없이 Postman 앱을 사용하려면 [OpenAPI 계약](docs/openapi.json)을 가져올 수 있습니다.

코드는 `app/`, 마이그레이션은 `migrations/`, 회귀 테스트는 `tests/`, 실행 가능한 Postman v3 컬렉션은 `postman/collections/firstlisten/`에 있습니다.

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

Android 수집기와 최소 권한·조회 화면은 필수입니다. 별도 웹 프론트엔드는 후순위로 둡니다.

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
