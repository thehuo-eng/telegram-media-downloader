# Telegram Smart Downloader 인계

- 버전: `3.0.0-smart` (2026-10-27)
- 정식 저장소: 현재 폴더의 Git 저장소
- Fork: `https://github.com/thehuo-eng/telegram-media-downloader`
- 작업 브랜치: `codex/smart-downloader`
- 원본 기준: `671d91526cd7d9a0dee6fef1d644f30a47b30797`
- 완료 소스 커밋: `4e4b11de05467ad49394bc7655e39f24b4319cb3` (로컬·Fork 동일)
- 소스 완료 후 기록 문서 커밋이 추가됩니다. `gvm-updates.json`은 위 소스 커밋을 가리키며 문서 커밋을 가리키도록 바꾸지 않습니다.

## 완료

기존 PySide6·Telethon 인증, FastTelethon, SQLite를 유지하면서 한국어 스마트 화면을 추가했습니다. 범주 CRUD·키워드/확장자·폴더·우선순위, 전체 형식 필터, 여러 채팅·전체 이력/기간/토픽 수집, 파일 선택·분류 미리보기·수동 지정, 전역 SHA-256 중복 방지와 기존 파일 인덱싱, 큐·재시도·일시정지/재개·충돌 없는 저장·종료 복구를 구현했습니다.

주요 코드: `src/smart/`, `src/ui/views/smart_view.py`, `category_view.py`, `src/ui/components/smart_table.py`. 원본 MIT 라이선스를 보존했습니다. `.env.local`, `config.json`은 Git 추적을 해제했으며 기존 로컬 파일은 보존했습니다.

## 검증과 실행본

- 로컬 자동 테스트: 97개 통과. 모의 Telegram 및 원본 회귀 테스트 포함.
- GitHub의 별도 Windows 환경에서도 테스트·EXE 빌드·GUI 검증·산출물 업로드 성공: [실행 #1](https://github.com/thehuo-eng/telegram-media-downloader/actions/runs/40481690930).
- 25,000행 Qt 모델과 한글 경로·설정·내용 중복·동시 다운로드·중단 복구 검증.
- Windows x64 EXE 실제 빌드 및 별도 폴더에서 시작·종료 성공. 스마트 탭 5개, 종료 코드 0.
- `dist/TelegramSmartDownloader.exe`: 52,972,660바이트.
- SHA-256: `f11b089a4b075875de2055d717c0ae17d4756cbcec84c20912dbb0b769188cb3`.
- 바탕화면 배포·바로가기 생성 없음. Git Version Manager 자동 등록 및 화면 확인 없음.
- `tools/verify_exe.ps1`은 PowerShell 5.1과 7에서 검증했습니다. 외부 PATH의 잘못된 ICU DLL 포함 문제를 spec에서 해결했습니다.

개발 실행: `.venv\Scripts\python.exe src\gui.py`. 빌드: `.\build_windows.ps1`. 사용법은 `README.ko.md`, 설계·테스트 대응표는 `docs/SMART_ARCHITECTURE.md`, 실행 증거 요약은 `docs/VALIDATION.md`를 참고하세요.

## 남은 확인

실제 계정 로그인·실채팅 수집·실제 대용량 전송은 사용자 계정으로 확인해야 합니다. 개발 중 임의 Telegram 로그인은 하지 않았습니다. 다른 Windows 10/11 PC와 장시간 부하, 디지털 서명/설치 프로그램은 미검증·미구현입니다. 기존 화면 일부는 영어를 유지합니다. 프로그램 밖에서 파일을 이동하면 재인덱싱해야 합니다.

개발 환경 `.venv`, 테스트 데이터 `.test-data`, 빌드 `build`/`dist`는 Git에서 제외됩니다. 이 폴더나 사용자 데이터 정리는 별도 승인 없이 수행하지 마세요. 소스 백업은 전체 폴더 복사 대신 Git 커밋을 사용합니다.
