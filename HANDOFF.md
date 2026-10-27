# Telegram 파일 자동 분류 인계

- 현재 버전: **3.1.0-smart** (2026-10-27)
- 정식 저장소: 현재 폴더의 Git 저장소
- Fork: `https://github.com/thehuo-eng/telegram-media-downloader`
- 작업 브랜치: `codex/smart-downloader`
- 완료 소스 커밋: `9f0c03a952542f51de0b7c2791c15614b2d25ba7` (로컬·Fork 동일)
- 이전 API 기능 소스: `4e4b11de05467ad49394bc7655e39f24b4319cb3`
- 완료 기록은 소스 커밋을 가리킵니다. 이후 작은 문서 커밋으로 기록을 저장하며 그 문서 SHA로 기록을 바꾸지 않습니다.

## 현재 동작

사용자 요청에 따라 기본 실행을 **API 없는 로컬 파일 분류**로 바꿨습니다. Telegram Desktop에서 내보내기를 완료한 폴더를 읽고 PDF를 기본 선택합니다. 기존 범주·확장자·수동 분류·미리보기·SHA-256·대기열을 재사용합니다. 기본 실행은 인증 정보를 불러오거나 Telegram 클라이언트를 시작하지 않습니다. 기존 API 모드는 `--telegram-api`로 명시적으로 실행할 때만 사용합니다.

원본 보존 복사와 사용자 확인 후 이동을 제공합니다. 같은 볼륨 이동은 검증 후 rename으로 전체 사본을 만들지 않습니다. 다른 볼륨은 복사·검증 후 원본을 제거합니다. 중복 원본은 자동 삭제하지 않습니다. 원본·목적지 중첩, 변경된 파일, 미완료 파일을 보호하고 임시 파일 검증 재개와 저장 직후 종료 복구를 지원합니다.

주요 추가: `src/smart/local.py`, `local_controller.py`, `src/ui/views/local_view.py`, `tests/test_local_files.py`, `test_local_gui.py`. 공유 저장·분류 모듈과 원본 MIT 라이선스, 기존 DB/인증 파일은 보존했습니다.

## 검증과 실행본

- 전체 자동 테스트 **116개 통과 / 25.64초**. 실제 100MiB 파일 복사·해시 검증 포함.
- [GitHub Windows CI](https://github.com/thehuo-eng/telegram-media-downloader/actions/runs/40490723367)에서도 테스트·빌드·EXE 실행 검사·산출물 업로드 성공.
- 일반 실행에서 인증 로드·Telegram 시작을 금지한 검증과 실제 EXE 시작·종료 검증 통과.
- EXE: `dist/TelegramFileOrganizer.exe`, **52,998,325바이트**, Windows x64.
- SHA-256: `baf3eba8290fb8c81da607b62d52413accbda599843fabab19bded5f845ef037`.
- 로컬 모드·폴더 선택·탭 5개·종료 코드 0 확인. 어두운/밝은 화면 확인.
- 이전 `TelegramSmartDownloader.exe`는 삭제하지 않았습니다. 새 파일을 사용해야 합니다.
- 바탕화면 복사·바로가기 생성 없음. Git Version Manager 자동 등록/화면 표시는 미확인.

개발 실행: `.venv\Scripts\python.exe src\gui.py`. 새 EXE 빌드: `.\build_windows.ps1`. 사용법·공간 계산은 `README.ko.md`, 실제 검증 범위는 `docs/VALIDATION.md`를 참고하세요.

## 남은 확인과 작업 규칙

실제 2TB/20,000개 PDF 전체 처리 시간, 다른 Windows PC, 실제 다른 드라이브 이동은 미검증입니다. 다른 볼륨 분기는 모의 조건으로 검사했습니다. Telegram의 8MB/4000MB 내보내기 설정은 개별 파일 제한이며 원본 다운로드는 공식 앱에서 사용자가 수행합니다.

사용자의 실제 파일로 임의 시험하지 않았습니다. 이동은 원본 위치를 변경하므로 앱에서 선택 대상·용량·폴더를 확인한 뒤 승인해야 합니다. `.venv`, `.test-data`, `build`, `dist` 및 사용자 데이터는 별도 정리 승인 없이 삭제하지 않습니다. 소스 보관은 전체 폴더 복사 대신 Git을 사용합니다.
