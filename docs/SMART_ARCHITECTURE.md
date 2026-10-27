# 스마트 다운로드 개발 메모

## 원본 조사 결과와 재사용

기준 저장소는 `vinodkr494/telegram-media-downloader`, 기준 HEAD는 `671d91526cd7d9a0dee6fef1d644f30a47b30797`입니다. 시작 시 작업 폴더는 변경 파일이 없는 빈 Git 저장소였으며, 원본 이력을 가져와 `codex/smart-downloader`에서 작업했습니다.

| 항목 | 원본 구현 | 스마트 기능 연결 |
|---|---|---|
| 인증 | `TelegramWorker`, Telethon, `.env` / `.session`, OTP·2FA | 같은 워커·클라이언트 사용, 한국어 로그인·입력 검증 |
| 수집 | 링크/ID 해석, 유형별 `get_messages`, 미디어 캐시 | 기존 입력 해석 재사용, `iter_messages(limit=None)` 전체 이력·기간·토픽·취소 |
| 다운로드 | asyncio 병렬 큐, FastTelethon 512 KiB 청크, FloodGate | 같은 FastTelethon 엔진을 전용 임시 경로에 연결, 순차 스트리밍 폴백 |
| 복구 | `.part` / `.meta`, 기존 task DB | 청크 크기·메타데이터 검증, SHA-256·저장 의도 기록·일시정지 복구 |
| 중복 | 채팅/메시지, 파일명·크기 및 기존 경로 | 계정/채팅/메시지/슬롯/파일 ID, 전역 파일 카탈로그, SHA-256 |
| SQLite | `media_cache`, `tasks`, JSON 마이그레이션 | 기존 테이블 보존, `smart_*` 테이블만 추가 |
| UI | PySide6 MainWindow, 로그인·설정·대기열·파일 관리 | 스마트 화면 5개 탭, Qt 모델 테이블, 범주 편집 |
| 빌드 | PyInstaller spec와 GitHub Actions | 스마트 전용 spec, PowerShell 실행·빌드, Windows CI |

전체 UI나 인증 엔진을 대체하지 않았습니다. 기존 기능은 사이드바에서 계속 열 수 있고 기존 이력도 기존 파일 화면에 남습니다. 계정 정보가 없던 기존 이력을 새 계정의 완료 이력으로 임의 해석하지 않습니다. 기존 폴더를 스마트 인덱싱에 등록하면 내용 중복 후보로 사용할 수 있습니다.

## 모듈과 불변 조건

- `src/smart/rules.py`: 일반 문자열 OR 매칭, NFKC/casefold, 확장자 필터, 우선순위, Windows 파일명 정리. 미리보기와 enqueue가 같은 `Classification` 객체를 사용합니다.
- `src/smart/store.py`: 추가 스키마, 범주·설정·메타데이터·수동 지정·큐·카탈로그·사유 이벤트. WAL과 짧은 배치 트랜잭션, 크기 인덱스, 스트리밍 SHA-256.
- `src/smart/pipeline.py`: 계정별 수집, 제한 없는 전체 페이지 조회, 날짜·토픽, 취소, 제한된 네트워크 재시도, 서버 FloodWait 대기, 다운로드 검증.
- `src/smart/controller.py`: 기존 워커의 asyncio 루프와 GUI 사이의 시그널. 인덱싱·목록 구성·해시는 GUI 밖에서 처리합니다. 오래된 목록 스냅샷이 새 수동 지정을 덮어쓰지 않도록 세대 번호를 사용합니다.
- `src/ui/components/smart_table.py`: QAbstractTableModel/QSortFilterProxyModel과 편집 시에만 생성하는 범주 delegate. 행마다 QWidget을 생성하지 않습니다.
- `src/ui/views/smart_view.py`, `category_view.py`: 채팅 선택, 파일 형식·미리보기, 범주, 큐/완료 파일, 설정·인덱싱.

같은 계정의 같은 Telegram 파일은 파일별 asyncio 잠금으로 다운로드를 직렬화합니다. 최종 내용 비교·저장은 DB별 프로세스 내 잠금으로 직렬화하고, 실행 시 QLockFile로 동일 DB의 중복 실행을 차단합니다. Windows의 덮어쓰기 없는 rename(다른 플랫폼은 exclusive hardlink)을 사용합니다. 최종 경로와 SHA-256을 먼저 저장해 파일 게시 후 프로세스 종료를 복구합니다. 새 임시 파일만 정리하며 기존 파일을 자동 삭제하지 않습니다.

인덱싱은 크기·수정 시간만 수집하고 내용 해시는 후보 비교 시 계산합니다. 이미 해시가 다르며 메타데이터도 바뀌지 않은 후보는 재해시를 생략합니다. 해시가 같은 후보는 실제 내용을 다시 확인하여 원본이 수정된 경우 잘못 생략하지 않습니다. 외부에서 추가·이동한 파일은 재인덱싱이 필요합니다.

기존 엔진에도 불완전한 청크 완료 판정 방지, 완료 메타데이터 전 디스크 flush, 잘못된 메타 인덱스 무시, finalizer 덮어쓰기 금지, 빈 파일 보존과 sidecar 덮어쓰기 금지를 적용했습니다.

## 요구 테스트 대응표

| 요구 사례 | 자동 테스트 |
|---|---|
| 1–7: 한글, 대소문자, OR, 충돌, 확장자, 미분류, 수동 | `test_smart_rules.py`, `test_smart_gui.py` |
| 8: 다른 채팅의 동일 메시지 ID 및 다른 계정 | `test_account_chat_and_edited_message_identity` |
| 9–12: 같은/다른 이름·내용·저장 폴더 | `test_smart_store.py`의 중복·충돌·인덱싱 테스트 |
| 13–14: 재시작과 분류된 최종 위치 재사용 | `test_restart_manual_settings_and_classified_history`, `test_end_to_end_download_preview_folder_and_history_skip` |
| 15: 중단·복구·저장 중 종료 | `test_pause_restart_resume_uses_partial_offset`, `test_crash_between_publication_and_catalog_is_recoverable` |
| 16: Windows 한글·특수문자 경로 | `test_safe_windows_names`, `test_same_name_different_content_and_empty_existing_file` |
| 17: 설정 저장·로드 | `test_smart_gui_offline_settings_and_filter_round_trip` |
| 18: 대량 GUI 목록 | `test_large_list_uses_model_and_event_loop_remains_responsive` (25,000행) |
| 추가: 전체 이력, 취소, 재시도, FloodWait | `test_smart_pipeline.py` |
| 추가: 동시 중복, 기존 빈 파일, 청크 손상 | `test_smart_store.py`, `test_smart_engine_safety.py` |

실계정 통합 테스트는 자동 테스트에 포함하지 않습니다. 자동 테스트는 임시 DB·파일·모의 Telegram만 사용합니다. 최종 실행 결과와 EXE 정보는 [검증 보고서](VALIDATION.md)에 기록합니다.
