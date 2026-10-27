# 검증 보고서

검증일: 2026-10-27 (한국 시간). 버전: `3.0.0-smart`.

## 실제 수행 결과

| 검증 | 결과 |
|---|---|
| Python 자동 테스트 | **97개 통과**, 18.15초. 원본 회귀 테스트 포함 |
| 테스트 환경 | Windows x64 (OS 빌드 26200), Python 3.12.10, PySide6 6.12.0 |
| 문법·공백 검사 | `compileall` 및 `git diff --check` 통과 |
| 대량 파일 GUI | 가상 파일 25,000행의 Qt 모델·검색·이벤트 루프 응답 테스트 통과 |
| 화면 검사 | 밝은/어두운 테마, 분류 미리보기, 범주 편집, 설정 화면 렌더링 확인 |
| 개발 실행 | `src/gui.py --smoke-test`로 창 생성 및 정상 종료 확인 |
| Windows EXE | PyInstaller 6.22.3으로 실제 빌드, PE x64 (`0x8664`) 확인 |
| EXE 실행 | 별도 데이터 폴더에서 GUI 생성·스마트 탭 5개·종료 코드 0 확인 |
| 빌드 검증 스크립트 | PowerShell 7 및 Windows 기본 PowerShell 5.1에서 실행 통과 |
| 패키지 내용 | 세션·인증 설정·사용자 DB 및 충돌한 외부 ICU DLL이 포함되지 않음 |
| GitHub Windows CI | 별도 Windows 환경의 테스트·EXE 빌드·GUI 시작/종료·산출물 업로드 모두 통과 |

자동 테스트와 EXE 시작 검사는 실제 Telegram 계정 없이 수행했습니다. EXE 검증 결과의 `telegram_started`는 `false`입니다. GUI 성능 검증은 모의 메타데이터와 로컬 Qt 모델을 대상으로 하며 실제 Telegram 수만 파일의 수집 시간을 측정한 결과가 아닙니다.

원격 검증은 소스 커밋 `4e4b11de05467ad49394bc7655e39f24b4319cb3`의 [GitHub Actions 실행 #1](https://github.com/thehuo-eng/telegram-media-downloader/actions/runs/40481690930)에서 성공했습니다. 이 실행 페이지에서 `TelegramSmartDownloader-Windows-x64` 산출물을 받을 수 있습니다. 아래 크기와 해시는 로컬 EXE 기준이며 원격 빌드 파일과 구별합니다.

## 빌드 산출물

- 경로: `dist/TelegramSmartDownloader.exe`
- 파일 크기: **52,972,660바이트** (약 50.5 MiB)
- 빌드 시각: **2026-10-27 18:26:44 +09:00**
- SHA-256: `f11b089a4b075875de2055d717c0ae17d4756cbcec84c20912dbb0b769188cb3`
- 형태: Python을 포함한 Windows x64 단일 EXE, 디지털 서명 없음
- 배치 상태: 프로젝트 `dist`에 생성. 바탕화면 복사·바로가기 및 설치 프로그램은 만들지 않음

EXE는 Git 소스에 포함하지 않습니다. 이 해시는 위 빌드 파일의 식별값이며 새로 빌드한 파일은 시간·환경에 따라 해시가 달라질 수 있습니다.

초기 EXE 검사에서 다른 도구의 PATH에 있던 동명 ICU DLL이 포함되어 Qt 로딩이 실패했습니다. spec의 DLL 탐색 환경을 제한하고 Windows 시스템 ICU를 사용하도록 수정한 뒤 위 EXE의 실제 실행으로 해결을 확인했습니다. 재발을 확인할 수 있도록 `tools/verify_exe.ps1`을 빌드 스크립트와 Windows CI에 연결했습니다.

## 재현 명령

저장소 루트에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\build_windows.ps1
# 이미 빌드된 파일의 시작·종료만 검사
.\tools\verify_exe.ps1
```

`verify_exe.ps1`은 `.test-data` 아래 새 폴더에서 EXE를 실행하고 JSON 결과와 화면 이미지를 남깁니다. 기존 사용자 데이터를 읽거나 Telegram에 로그인하지 않습니다. 실행 제한 시간을 넘기면 자신이 시작한 검증 프로세스만 종료합니다.

## 아직 검증하지 않은 항목

- 실제 계정의 OTP/2FA 로그인, 실채팅 전체 이력, 비공개 그룹과 실제 포럼 토픽
- 실제 대용량 전송 속도, 네트워크 장기 단절 및 Telegram 서버에서 발생한 FloodWait
- 다른 Windows 10/11 PC, 수십만 파일의 장기 부하, 백신 및 디지털 서명 배포

일부 기존 화면에는 영어가 남아 있습니다. 기존 파일의 임의 외부 이동은 자동 추적하지 않으므로 이동 후 재인덱싱해야 합니다. 완료 파일의 범주를 변경해도 원본을 자동 이동하지 않습니다. 세부 사용·복구 방법은 [한국어 설명서](../README.ko.md), 요구사항별 테스트는 [개발 메모](SMART_ARCHITECTURE.md)를 참고하세요.
