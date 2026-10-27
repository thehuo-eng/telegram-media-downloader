from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QCheckBox, QFileDialog, QMessageBox, QProgressBar, QComboBox)

from smart.local import LocalStore
from smart.local_controller import LocalController
from smart.store import ACTIVE
from ui.components.smart_table import file_size
from ui.views.smart_view import SmartView


class LocalView(SmartView):
    store_type = LocalStore
    controller_type = LocalController
    local_mode = True

    def __init__(self, worker, db_path, parent=None):
        super().__init__(worker, db_path, parent)
        self.account_label.setText("로컬 파일 모드 · API / 로그인 불필요")
        self.status.setText("내보내기가 끝난 폴더를 추가하고 파일을 읽으세요. 기본 형식은 PDF입니다.")
        self.search.setPlaceholderText("파일명 / 원본 폴더 검색")
        self.extra_ext.setPlaceholderText("분류할 확장자: pdf, hwpx 등")
        self.download_button.setText("체크한 파일 분류 시작")
        self.queue_count.setText("저장된 분류 이력이 없습니다.")

    def build_chats(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("Telegram Desktop에서 내려받은 파일을 이 PC에서 분류합니다. API 키와 Telegram 로그인이 필요하지 않습니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        guide = QLabel("내보내기: ‘파일’ 체크 → 크기 제한을 파일 크기보다 높게 설정 → 경로 지정 → 내보내기 완료 후 이곳에 폴더 추가.\n"
            "8MB / 4000MB는 파일 한 개당 제한입니다. 100MB 파일 2만 개는 총 약 2TB이므로 여유 공간을 확인하세요. HTML·JSON 모두 실제 파일 폴더를 읽을 수 있습니다.")
        guide.setWordWrap(True)
        layout.addWidget(guide)
        self.source_folders = QListWidget()
        self.source_folders.addItems(self.store.setting("local_sources", []))
        layout.addWidget(self.source_folders)
        toolbar = QHBoxLayout()
        add = QPushButton("원본 폴더 추가")
        add.clicked.connect(self.add_source)
        toolbar.addWidget(add)
        remove = QPushButton("선택 폴더를 목록에서 제외")
        remove.clicked.connect(lambda: self.source_folders.takeItem(self.source_folders.currentRow()))
        toolbar.addWidget(remove)
        self.recursive = QCheckBox("하위 폴더 포함")
        self.recursive.setChecked(self.store.setting("local_recursive", True))
        toolbar.addWidget(self.recursive)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        note = QLabel("원본 폴더와 최종 저장 폴더는 서로 겹치지 않게 지정하세요. 임시 다운로드 파일과 링크 폴더는 제외합니다. 원본을 수정하지 않고 목록부터 읽습니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        self.scan_button = QPushButton("폴더 읽기 → 분류 미리보기")
        self.scan_button.setObjectName("PrimaryButton")
        self.scan_button.clicked.connect(self.scan)
        actions.addWidget(self.scan_button)
        cancel = QPushButton("읽기 취소")
        cancel.clicked.connect(self.controller.scan_cancel.set)
        actions.addWidget(cancel)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 1)
        self.scan_progress.setTextVisible(False)
        actions.addWidget(self.scan_progress)
        layout.addLayout(actions)
        self.tabs.addTab(page, "1. 원본 폴더")

    def add_source(self):
        path = QFileDialog.getExistingDirectory(self, "내보내기가 끝난 원본 폴더")
        if path and path not in [self.source_folders.item(i).text() for i in range(self.source_folders.count())]:
            self.source_folders.addItem(path)

    def scan(self):
        sources = [self.source_folders.item(i).text() for i in range(self.source_folders.count())]
        if not sources:
            QMessageBox.information(self, "원본 폴더", "내보내기가 끝난 폴더를 추가하세요.")
            return
        self.store.set_setting("local_recursive", self.recursive.isChecked())
        self.controller.scan(sources, recursive=self.recursive.isChecked())

    def build_preview(self):
        super().build_preview()
        row = QHBoxLayout()
        row.addWidget(QLabel("저장 방식"))
        self.operation = QComboBox()
        self.operation.addItem("복사 — 원본 보존", "copy")
        self.operation.addItem("이동 — 저장 완료 후 원본 제거", "move")
        # Destructive move permission is deliberately not carried into the next launch.
        row.addWidget(self.operation)
        tip = QLabel("같은 드라이브의 이동은 추가 전체 사본을 만들지 않습니다. 중복 원본은 두 방식 모두 유지합니다.")
        tip.setWordWrap(True)
        row.addWidget(tip, 1)
        self.tabs.widget(1).layout().insertLayout(3, row)
        self.operation.currentIndexChanged.connect(self.update_counts)

    def update_counts(self, *_):
        super().update_counts()
        rows = [r for r in self.preview_model.rows if r["selected"] and r["plan"].allowed and r["phase"] not in ACTIVE]
        total = sum(r["size"] for r in rows)
        self.count_label.setText(f"전체 {len(self.preview_model.rows):,}개 · 체크 {len(rows):,}개 / {file_size(total)}\n"
                                "숨겨진 체크 포함 · 복사는 중복을 제외한 만큼 추가 공간 필요")

    def download_selected(self):
        rows = [r for r in self.preview_model.rows if r["selected"] and r["plan"].allowed and r["phase"] not in ACTIVE]
        if not rows:
            QMessageBox.information(self, "파일 선택", "분류할 파일을 체크하세요.")
            return
        mode = self.operation.currentData()
        if mode == "move":
            roots = list(dict.fromkeys(r["source_root"] for r in rows))
            text = (f"체크한 {len(rows):,}개 / {file_size(sum(r['size'] for r in rows))}를 미리보기 경로로 이동합니다.\n"
                "저장·검증이 끝난 파일은 원본 위치에서 제거됩니다. 기존 내보내기 HTML의 링크가 끊길 수 있습니다.\n"
                "중복 파일의 원본은 삭제하지 않습니다. 원본 파일은 Git으로 복구되지 않습니다.\n\n원본 폴더:\n" + "\n".join(roots[:8]))
            if QMessageBox.question(self, "선택한 원본 파일 이동", text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        self.controller.start_downloads([(r["item_key"], r["plan"]) for r in rows], mode=mode)
        self.tabs.setCurrentIndex(3)

    def save_settings(self):
        ok = super().save_settings()
        if ok:
            self.status.setText("설정을 저장했습니다. 이미 대기열에 넣은 파일은 확인한 경로와 복사·이동 방식을 유지합니다.")
        return ok
