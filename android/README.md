# FirstListen Android

YouTube Music의 미디어 세션을 관찰해 청취 시간을 기기에 저장하고 기존 FastAPI 서버로 전송하는 Kotlin / Jetpack Compose 앱입니다. Android 8.0(API 26) 이상을 지원합니다.

## 실행

1. 저장소 루트에서 `docker compose up --build -d`로 백엔드를 실행합니다.
2. Android Studio에서 **이 디렉터리(`android/`)**를 프로젝트로 엽니다.
3. Gradle JDK를 **JDK 21**로 설정하고 SDK Manager에서 **Android SDK Platform 36.1**, **Build Tools 36.0.0**을 설치합니다.
4. 앱을 실행한 뒤 서버 주소, 이메일, 비밀번호를 입력합니다. 회원가입 버튼은 가입 후 로그인까지 수행합니다. 비밀번호는 서버 기준 10자 이상입니다.
5. **알림 접근 설정**에서 FirstListen을 허용하고 앱으로 돌아와 **청취 기록 수집**을 켭니다.
6. YouTube Music에서 한 곡을 30초 이상 재생합니다. 최근 기기 기록과 서버의 `/api/v1/tracks` 및 `/api/v1/tracks/{id}/stats`에서 결과를 확인합니다.

서버 주소:

앱의 초기 서버 주소는 USB 실기기용 `http://127.0.0.1:8000`입니다. USB로 연결한 뒤 아래 명령을 실행하면 휴대폰의 8000 포트를 PC 서버에 연결합니다. USB를 분리하거나 휴대폰을 재부팅한 후에는 다시 설정해야 할 수 있습니다.

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" -d reverse tcp:8000 tcp:8000
```

에뮬레이터에서 USB 포트 연결 설정 없이 PC 서버를 사용하려면 주소를 `http://10.0.2.2:8000`으로 바꿉니다. 기존에 로그인한 서버 주소는 유지됩니다.

| 환경 | 주소 |
| --- | --- |
| Android Emulator → 개발 PC | `http://10.0.2.2:8000` |
| USB 실제 기기 + `adb reverse tcp:8000 tcp:8000` | `http://127.0.0.1:8000` |
| 같은 Wi-Fi의 실제 기기 | `http://개발-PC의-LAN-IP:8000` (방화벽 허용 필요) |
| 배포 서버 | `https://서버주소` |

HTTP는 debug 빌드에서만 허용합니다. release 빌드는 HTTPS 주소를 요구합니다. HTTP 리다이렉트는 토큰이 다른 서버로 전달되지 않도록 따르지 않습니다. 서버 주소를 변경하면 별도의 보관함으로 취급합니다.

Windows PowerShell에서 Android Studio의 JDK를 이용해 빌드할 수도 있습니다. SDK 위치는 자신의 환경에 맞춰 설정하세요.

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
.\gradlew.bat :core:test :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

APK는 `app/build/outputs/apk/debug/app-debug.apk`에 생성됩니다. Linux/macOS에서는 JDK 21과 Android SDK를 설정한 뒤 `sh gradlew`를 사용합니다. Gradle Wrapper와 의존성은 첫 실행 시 다운로드합니다.

## Google Takeout JSON 가져오기

로그인 후 **기록 → Google Takeout 가져오기 → JSON 파일 선택 및 가져오기**를 누릅니다. Google Takeout에서 내려받은 ZIP의 압축을 먼저 풀고 활동 기록 JSON 파일을 선택하세요. 파일을 선택하면 현재 계정으로 바로 업로드합니다. 알림 접근 권한은 필요하지 않습니다.

- 최대 100 MiB이며, 파일 전체를 메모리에 올리지 않고 앱 캐시에 복사한 뒤 인증된 `POST /api/v1/imports`의 multipart `file`로 전송합니다. 임시 사본은 성공·실패·취소 시 삭제합니다.
- 완료 화면에 새로 저장, 중복, 제외, 검토 필요, 오류 및 곡 수를 표시합니다. **내 곡에서 확인**을 누르면 목록을 새로 조회합니다. 가져온 기록의 재생 시간은 미확인이므로 시간 합계에서 제외합니다.
- 업로드·서버 처리 중에는 앱을 열어 두세요. 화면 회전 중에는 작업을 유지하며, 로그아웃·계정 변경 시 작업과 결과를 초기화합니다. 백그라운드 가져오기 및 프로세스 종료 후 자동 재개는 지원하지 않습니다.
- 연결이 끊겨 저장 결과를 확인하지 못했다면 같은 파일을 다시 선택할 수 있습니다. 서버는 기존 Takeout 기록을 중복 저장하지 않습니다. 검토 필요·오류 항목의 상세 조회 UI는 제공하지 않으며 해당 항목은 청취 기록에 추가되지 않습니다.

## 코드 구성

| 파일 / 모듈 | 역할 |
| --- | --- |
| `core/ListeningTracker.kt` | 재생 상태, 곡 변경, 반복, 청취 시간과 이벤트 UUID 관리 |
| `core/SyncEngine.kt` | 100개 배치, 전송 버전 확인, 계정 검증, 실패 배치 분리 |
| `app/.../capture/MusicNotificationListenerService.kt` | 알림 접근 서비스 수명 관리, 세션 연결, 순차 수집과 저장 |
| `app/.../capture/MediaSessionObserver.kt` | YouTube Music 세션의 메타데이터와 재생 상태 읽기 |
| `app/.../data/ListenDatabase.kt` | Room 이벤트 보관함, 업로드 확인, 오류 보관 |
| `app/.../data/SessionStore.kt` | Android Keystore AES-GCM으로 암호화한 로그인 정보 |
| `app/.../network/FirstListenApi.kt` | 인증·동기화·곡 조회·질문·Takeout JSON 업로드 API |
| `app/.../TakeoutImportViewModel.kt` | 파일 선택 계정 검증, 가져오기 상태·결과 및 임시 파일 관리 |
| `app/.../sync/ListenSyncWorker.kt` | 네트워크 조건, 지수 백오프, 일회성·주기 동기화 |
| `app/.../MainActivity.kt` | 로그인, 권한 설정, 수집 토글, 최근 기록·동기화 상태 |

## 수집 규칙

- 알림 접근 권한과 로그인 계정, 수집 토글이 모두 있어야 수집합니다. 세션 패키지는 `com.google.android.apps.youtube.music`으로 한정하며, 다른 앱의 알림 내용은 저장하지 않습니다.
- 활성 세션에는 `MediaController.Callback`을 연결하고, 연결 중에는 약 5초마다 상태를 확인해 Room에 체크포인트를 저장합니다. 네트워크 호출은 이 서비스에서 실행하지 않습니다.
- `STATE_PLAYING`인 구간의 **실제 경과 시간**을 누적합니다. 재생 위치를 총 청취 시간으로 사용하지 않으므로 탐색으로 건너뛴 길이는 합산되지 않습니다. 일시정지·버퍼링은 제외하며, 시간 간격은 `elapsedRealtime()`, 최초 관찰 시각은 UTC `Instant`를 사용합니다.
- 곡 변경과 재생 목록 항목 변경은 새 UUID를 만듭니다. 같은 곡의 일시정지·재개에는 기존 UUID를 유지하되 30분을 넘는 일시정지는 새 이벤트로 분리합니다.
- 같은 곡의 끝에서 시작으로 돌아가는 재생 상태 변경은 반복으로 판정합니다. 곡 끝부분에서 사용자가 직접 처음으로 탐색한 경우와 구분할 수 없는 경우가 있어, 반복 횟수는 실제 기기 검증이 필요합니다.
- 곡명이나 가수가 없으면 수집을 보류합니다. `MEDIA_ID` / `MEDIA_URI`에서 식별 가능한 YouTube ID를 얻으면 `external_id`로 쓰고, 나머지는 서버의 메타데이터 식별을 사용합니다. 이벤트 생성 후 전송용 곡 정보는 고정하여 뒤늦은 외부 ID 추가로 서버에서 `409`가 발생하지 않도록 합니다.
- 15초를 넘는 관찰 간격은 같은 곡의 재생 위치 진행으로 연속성을 확인할 때만 합산합니다. 수집 서비스 연결 해제·프로세스 종료·재부팅 사이의 청취는 추정하지 않습니다. 프로세스 종료 시 마지막 약 5초의 미저장 구간이 누락될 수 있습니다.
- 서비스가 다시 연결되면 새 관찰 이벤트로 시작하며, 저장된 전송 대기 기록은 그대로 재시도합니다. 따라서 한 번의 실제 청취가 서비스 재연결로 여러 이벤트가 될 수 있습니다. 강제 종료, 권한 해제, OS 제한 중의 무중단 수집은 보장하지 않습니다.
- 24시간을 넘는 이벤트는 새 UUID로 나누어 서버 상한을 지킵니다. 설치 전 청취 이력은 이 수집기로 복구하지 않습니다.

## 저장·전송 규칙

- 모든 이벤트는 Room에 먼저 저장합니다. 30초 미만 이벤트도 기기에 남기되 서버 전송 대상에서 제외합니다.
- 30초 도달, 이후 누적 시간 약 30초 증가, 이벤트 종료 시 일회성 동기화를 요청합니다. 오프라인 중에는 계정별 작업 한 개만 대기시킵니다. 15분 주기 작업은 요청 누락과 작업 종료 직후 갱신을 회수합니다. WorkManager 실행 시각은 OS가 조정하므로 실시간 전송은 보장하지 않습니다.
- `(서버 주소 + 회원 ID)`로 보관함을 분리합니다. 로그아웃하면 수집과 해당 계정의 전송 작업을 중단합니다. 전송 중 계정이 바뀌어도 원래 계정의 기록과 토큰만 사용하며, 다음 배치 전에 다시 계정을 확인합니다. 다른 계정으로 기존 기록을 보내지 않습니다.
- `localVersion`과 `uploadedVersion`을 구분합니다. 31초 데이터를 보내는 동안 45초로 늘면 31초 버전만 전송 완료로 표시하고 45초 버전은 남겨 둡니다. 서버 응답의 이벤트 ID, 상태, 곡 ID, 누적 시간도 확인한 후 완료 처리합니다.
- 연결 실패·일시적인 서버 오류는 동일 UUID와 누적 시간으로 재시도합니다. 서버의 최댓값 저장 방식 덕분에 응답을 잃어도 중복 합산하지 않습니다.
- `401`이면 재로그인을 기다리며 기기 기록은 보존합니다. 서버에 토큰 갱신 API가 없어 자동 refresh는 하지 않습니다.
- `409`·`422` 배치는 작은 배치로 나눠 정상 기록을 먼저 전송하고, 문제 이벤트는 오류와 함께 보류합니다. 화면에서 보류 기록을 확인하고 수동 재시도할 수 있습니다. 자동으로 UUID를 바꾸거나 문제 기록을 삭제하지 않습니다.
- 토큰은 앱 전용 저장소에서 Android Keystore 키로 암호화하며, 비밀번호는 저장하지 않습니다. 앱 데이터 백업은 비활성화합니다.

## 검증

JVM 테스트는 일시정지·버퍼링·탐색·반복·연결 해제·24시간 분리, 100개 배치, 전송 도중 갱신, 계정 전환, 응답 유실, 오류 배치 분리를 검사합니다. Robolectric 테스트는 실제 Room 쿼리와 DB 재열기 후 보존을, MockWebServer 테스트는 FastAPI JSON 계약과 인증 헤더·리다이렉트 차단을 검사합니다.

실제 기기에서는 아래 항목을 별도로 확인해야 합니다.

1. 곡명·가수·외부 ID·재생 상태가 YouTube Music에서 제공되는지 확인
2. 29초 건너뛰기, 31초 이상 재생, 일시정지·버퍼링·앞뒤 탐색
3. 같은 곡 반복, 같은 곡이 연속으로 있는 재생 목록
4. 화면 잠금, 앱 화면 닫기, 서비스 재연결, 재부팅
5. 오프라인 수집 후 연결, 토큰 만료 후 재로그인
6. Alice 로그아웃 → Bob 로그인 → Alice 재로그인 시 보관함 분리
7. 동일 UUID의 31초 → 120초 → 31초 재전송 후 서버 집계가 이벤트 1개·120초인지 확인

설계 근거: [미디어 세션 조회](https://developer.android.com/reference/android/media/session/MediaSessionManager), [알림 리스너 연결 수명](https://developer.android.com/reference/android/service/notification/NotificationListenerService), [시간 간격 측정](https://developer.android.com/reference/android/os/SystemClock), [WorkManager 조건·주기·재시도](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work).
