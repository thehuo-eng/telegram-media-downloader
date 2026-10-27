from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QDate, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QLabel,
    QPushButton, QLineEdit, QCheckBox, QListWidget, QListWidgetItem, QDateEdit, QSpinBox, QTableView,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox, QPlainTextEdit, QProgressBar, QComboBox,
    QScrollArea, QFormLayout)

from smart.controller import SmartController
from smart.rules import FILE_GROUPS, FileFilter, absolute_folder, extensions
from smart.store import ACTIVE, TERMINAL, SmartStore
from ui.components.smart_table import MediaTableModel, MediaProxy, CategoryDelegate
from ui.views.category_view import CategoryView


class SmartView(QWidget):
    login_requested = Signal()

    def __init__(self, worker, db_path, parent=None):
        super().__init__(parent)
        self.setObjectName("SmartView")
        self.store = SmartStore(db_path)
        self.controller = SmartController(worker, self.store, self)
        self.categories = self.store.categories()
        self.dirty = False
        self._snapshot = None
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        top = QHBoxLayout()
        title = QLabel("Telegram Smart Downloader")
        title.setStyleSheet("font-size: 21px; font-weight: 600;")
        top.addWidget(title)
        top.addStretch()
        self.account_label = QLabel("오프라인 · 저장된 설정을 사용할 수 있습니다")
        top.addWidget(self.account_label)
        login = QPushButton("텔레그램 연결")
        login.clicked.connect(self.login_requested.emit)
        top.addWidget(login)
        root.addLayout(top)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.build_chats()
        self.build_preview()
        self.category_view = CategoryView(self.store, lambda: self.controller.classifier().fallback)
        self.category_view.changed.connect(self.rules_changed)
        self.tabs.addTab(self.category_view, "3. 범주 · 키워드")
        self.build_queue()
        self.build_settings()
        self.status = QLabel("범주를 등록하고, 채팅방을 선택한 뒤 파일 목록을 수집하세요.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.controller.status.connect(self.status.setText)
        self.controller.error.connect(lambda text: QMessageBox.warning(self, "작업 확인", text))
        self.controller.account_changed.connect(self.account_changed)
        self.controller.dialogs_ready.connect(self.show_dialogs)
        self.controller.snapshot_ready.connect(self.show_snapshot)
        self.controller.changed.connect(self.mark_dirty)
        self.controller.activity.connect(self.activity_changed)
        self.controller.file_progress.connect(self.queue_model.set_progress)
        self.controller.file_progress.connect(self.preview_model.set_progress)
        self.controller.index_done.connect(self.index_done)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(600)
        self.refresh_timer.timeout.connect(self.refresh_if_dirty)
        self.refresh_timer.start()
        self.mark_dirty()

    def build_chats(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("접근 권한이 있는 채널·그룹·개인 채팅을 여러 개 선택할 수 있습니다. 전체 이력은 메시지 끝까지 조회합니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        toolbar = QHBoxLayout()
        self.dialogs_button = QPushButton("내 채팅방 불러오기")
        self.dialogs_button.clicked.connect(self.controller.list_dialogs)
        toolbar.addWidget(self.dialogs_button)
        self.chat_search = QLineEdit()
        self.chat_search.setPlaceholderText("채팅방 검색")
        self.chat_search.textChanged.connect(self.filter_chats)
        toolbar.addWidget(self.chat_search)
        for label, selected in [("표시된 채팅 전체 선택", True), ("전체 해제", False)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, value=selected: self.select_chats(value))
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.chats = QListWidget()
        self.chats.itemChanged.connect(self.save_chats)
        layout.addWidget(self.chats)
        self.sources = QLineEdit(self.store.setting("sources", ""))
        self.sources.setPlaceholderText("채널 ID, @username, 링크를 쉼표로 구분 (선택한 채팅방과 함께 수집)")
        layout.addWidget(self.sources)
        options = QHBoxLayout()
        self.all_history = QCheckBox("과거 전체 이력")
        self.all_history.setChecked(True)
        options.addWidget(self.all_history)
        self.limit = QSpinBox()
        self.limit.setRange(1, 1000000)
        self.limit.setValue(2000)
        self.limit.setSuffix("개 메시지 / 채팅")
        self.limit.setEnabled(False)
        self.all_history.toggled.connect(lambda value: self.limit.setEnabled(not value))
        options.addWidget(self.limit)
        self.topic = QSpinBox()
        self.topic.setRange(0, 2147483647)
        self.topic.setSpecialValueText("전체 토픽")
        options.addWidget(QLabel("토픽 ID"))
        options.addWidget(self.topic)
        options.addStretch()
        layout.addLayout(options)
        dates = QHBoxLayout()
        self.date_enabled = QCheckBox("기간 지정 (한국 시간)")
        self.start_date = QDateEdit(QDate.currentDate().addMonths(-1))
        self.end_date = QDateEdit(QDate.currentDate())
        dates.addWidget(self.date_enabled)
        for edit in (self.start_date, self.end_date):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setEnabled(False)
            self.date_enabled.toggled.connect(edit.setEnabled)
            dates.addWidget(edit)
        dates.addStretch()
        layout.addLayout(dates)
        actions = QHBoxLayout()
        self.scan_button = QPushButton("파일 목록 수집 → 미리보기")
        self.scan_button.setObjectName("PrimaryButton")
        self.scan_button.clicked.connect(self.scan)
        actions.addWidget(self.scan_button)
        cancel = QPushButton("조회 취소")
        cancel.clicked.connect(self.controller.scan_cancel.set)
        actions.addWidget(cancel)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 1)
        self.scan_progress.setValue(0)
        self.scan_progress.setTextVisible(False)
        actions.addWidget(self.scan_progress)
        layout.addLayout(actions)
        self.tabs.addTab(page, "1. 채팅방 선택")

    def make_table(self, model):
        table = QTableView()
        proxy = MediaProxy(table)
        proxy.setSourceModel(model)
        table.setModel(proxy)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(30)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate([48, 260, 140, 70, 95, 120, 220, 240, 230, 220, 320]):
            table.setColumnWidth(col, width)
        return table, proxy

    def build_preview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        filters = QGridLayout()
        self.filter_checks = {}
        saved = self.store.setting("filter", asdict(FileFilter()))
        for col, group in enumerate(list(FILE_GROUPS) + ["기타", "확장자 없음"]):
            cb = QCheckBox(group)
            cb.setChecked(group in saved["groups"])
            cb.toggled.connect(self.save_filter)
            filters.addWidget(cb, 0, col)
            self.filter_checks[group] = cb
        self.extra_ext = QLineEdit(", ".join(saved["extra_extensions"]))
        self.extra_ext.setPlaceholderText("추가 다운로드 확장자: dwg, psd 등")
        self.extra_ext.editingFinished.connect(self.save_filter)
        filters.addWidget(self.extra_ext, 1, 0, 1, 4)
        for col, (label, value) in enumerate([("모든 형식", True), ("형식 전체 해제", False)], 4):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, selected=value: self.select_formats(selected))
            filters.addWidget(button, 1, col, 1, 1)
        layout.addLayout(filters)
        help_text = QLabel("범주 셀을 두 번 클릭하면 수동 지정할 수 있습니다. 내용 중복은 내려받아 검사하기 전까지 미확인입니다. 같은 이름의 다른 파일에는 번호가 붙습니다.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("파일명 / 채팅방 검색")
        toolbar.addWidget(self.search)
        for label, value in [("표시된 파일 전체 선택", True), ("표시된 파일 선택 해제", False)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, selected=value: self.select_files(selected))
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.preview_model = MediaTableModel(parent=self)
        self.preview_model.manual_changed.connect(self.save_manual)
        self.preview_model.selection_changed.connect(self.save_selection)
        self.preview_table, self.preview_proxy = self.make_table(self.preview_model)
        self.preview_table.setItemDelegateForColumn(5, CategoryDelegate(lambda: self.categories, self.preview_table))
        self.search.textChanged.connect(self.preview_proxy.search)
        layout.addWidget(self.preview_table)
        actions = QHBoxLayout()
        self.count_label = QLabel("파일 0개")
        actions.addWidget(self.count_label)
        actions.addStretch()
        self.download_button = QPushButton("체크한 파일 다운로드")
        self.download_button.setObjectName("PrimaryButton")
        self.download_button.clicked.connect(self.download_selected)
        actions.addWidget(self.download_button)
        layout.addLayout(actions)
        self.tabs.addTab(page, "2. 파일 · 분류 미리보기")

    def build_queue(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        for label, fn in [("전체 일시정지", self.controller.download_cancel.set),
                          ("일시정지 / 대기 재개", lambda: self.controller.start_downloads()),
                          ("실패 파일 재시도", lambda: self.controller.start_downloads(retry=True)),
                          ("선택 파일 폴더 열기", self.open_folder)]:
            button = QPushButton(label)
            button.clicked.connect(fn)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        toolbar = QHBoxLayout()
        queue_search = QLineEdit()
        queue_search.setPlaceholderText("완료 파일 / 대기열 검색")
        toolbar.addWidget(queue_search)
        phase = QComboBox()
        for text, values in [("전체 상태", None), ("진행 / 대기", list(ACTIVE)), ("완료 / 중복", list(TERMINAL)),
                             ("실패", ["failed"]), ("일시정지", ["paused"])]:
            phase.addItem(text, values)
        toolbar.addWidget(phase)
        layout.addLayout(toolbar)
        self.queue_model = MediaTableModel(queue=True, parent=self)
        self.queue_table, self.queue_proxy = self.make_table(self.queue_model)
        self.queue_table.setColumnHidden(0, True)
        self.queue_table.doubleClicked.connect(self.open_folder)
        queue_search.textChanged.connect(self.queue_proxy.search)
        def filter_phase():
            self.queue_proxy.set_phases(phase.currentData())
        phase.currentIndexChanged.connect(filter_phase)
        layout.addWidget(self.queue_table)
        self.total_progress = QProgressBar()
        self.total_progress.setFormat("처리 완료 %v / %m개 (%p%)")
        layout.addWidget(self.total_progress)
        self.queue_count = QLabel("저장된 다운로드 이력이 없습니다.")
        layout.addWidget(self.queue_count)
        self.tabs.addTab(page, "4. 대기열 · 완료 파일")

    def build_settings(self):
        body = QWidget()
        layout = QFormLayout(body)
        self.fallback = QLineEdit(self.controller.classifier().fallback)
        row = QHBoxLayout()
        row.addWidget(self.fallback)
        choose = QPushButton("폴더 선택")
        def choose_fallback():
            path = QFileDialog.getExistingDirectory(self, "미분류 저장 폴더", self.fallback.text())
            if path:
                self.fallback.setText(path)
        choose.clicked.connect(choose_fallback)
        row.addWidget(choose)
        layout.addRow("미분류 저장 폴더", row)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 8)
        self.concurrency.setValue(self.store.setting("concurrency", 3))
        layout.addRow("동시 다운로드 파일 수", self.concurrency)
        self.speed = QSpinBox()
        self.speed.setRange(0, 1000000)
        self.speed.setSpecialValueText("제한 없음")
        self.speed.setSuffix(" KB/s (파일당)")
        self.speed.setValue(self.store.setting("max_speed_kb", 0))
        layout.addRow("속도 제한", self.speed)
        info = QLabel("모든 범주 폴더와 미분류 폴더를 중복 검사 대상으로 사용합니다. 추가로 관리할 기존 폴더를 아래에 등록할 수 있습니다.")
        info.setWordWrap(True)
        layout.addRow(info)
        self.extra_folders = QPlainTextEdit("\n".join(self.store.setting("extra_folders", [])))
        self.extra_folders.setMaximumHeight(120)
        layout.addRow("추가 관리 폴더 (한 줄에 하나)", self.extra_folders)
        add = QPushButton("기존 폴더 추가")
        def add_folder():
            path = QFileDialog.getExistingDirectory(self, "추가 관리 폴더")
            if path:
                self.extra_folders.appendPlainText(path)
        add.clicked.connect(add_folder)
        layout.addRow(add)
        save = QPushButton("설정 저장")
        save.clicked.connect(self.save_settings)
        layout.addRow(save)
        indexing = QLabel("기존 파일 인덱싱은 파일을 수정하지 않고 위치·크기를 등록합니다. 다운로드 후 크기가 같은 후보만 SHA-256으로 검사합니다. 새 파일을 이 폴더에 추가했다면 다시 인덱싱하세요.")
        indexing.setWordWrap(True)
        layout.addRow(indexing)
        row = QHBoxLayout()
        self.index_button = QPushButton("기존 파일 인덱싱 시작")
        self.index_button.clicked.connect(self.start_index)
        cancel = QPushButton("인덱싱 취소")
        cancel.clicked.connect(self.controller.index_cancel.set)
        row.addWidget(self.index_button)
        row.addWidget(cancel)
        layout.addRow(row)
        self.index_result = QLabel("아직 기존 파일을 인덱싱하지 않았습니다.")
        self.index_result.setWordWrap(True)
        layout.addRow(self.index_result)
        location = QLabel(f"설정·이력 DB: {self.store.path}")
        location.setWordWrap(True)
        location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addRow(location)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(body)
        self.tabs.addTab(area, "5. 설정 · 중복 검사")

    def account_changed(self, account):
        self.account_label.setText(f"연결됨 · 계정 {account}" if account else "오프라인 · 저장된 기록")
        self.chats.clear()
        self.preview_model.replace([], self.controller.classifier())
        self.queue_model.replace([], self.controller.classifier())
        self.mark_dirty()

    def show_dialogs(self, dialogs):
        saved = set(self.store.setting(f"chats:{self.controller.account}", []))
        self.chats.blockSignals(True)
        self.chats.clear()
        for dialog in dialogs:
            item = QListWidgetItem(f"{dialog['title']}  ({dialog['id']})")
            item.setData(Qt.UserRole, dialog["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if dialog["id"] in saved else Qt.Unchecked)
            self.chats.addItem(item)
        self.chats.blockSignals(False)
        self.filter_chats(self.chat_search.text())

    def filter_chats(self, text):
        for i in range(self.chats.count()):
            item = self.chats.item(i)
            item.setHidden(text.casefold() not in item.text().casefold())

    def select_chats(self, selected):
        self.chats.blockSignals(True)
        for i in range(self.chats.count()):
            item = self.chats.item(i)
            if not selected or not item.isHidden():
                item.setCheckState(Qt.Checked if selected else Qt.Unchecked)
        self.chats.blockSignals(False)
        self.save_chats()

    def save_chats(self, *_):
        if self.controller.account:
            self.store.set_setting(f"chats:{self.controller.account}", [self.chats.item(i).data(Qt.UserRole)
                for i in range(self.chats.count()) if self.chats.item(i).checkState() == Qt.Checked])

    def scan(self):
        sources = [self.chats.item(i).data(Qt.UserRole) for i in range(self.chats.count()) if self.chats.item(i).checkState() == Qt.Checked]
        sources.extend(x.strip() for x in self.sources.text().split(",") if x.strip())
        if not sources:
            QMessageBox.information(self, "채팅방 선택", "채팅방을 체크하거나 ID·링크를 입력하세요.")
            return
        self.store.set_setting("sources", self.sources.text())
        start = end = None
        if self.date_enabled.isChecked():
            kst = timezone(timedelta(hours=9))
            start = datetime.combine(self.start_date.date().toPython(), time.min, tzinfo=kst)
            end = datetime.combine(self.end_date.date().toPython() + timedelta(days=1), time.min, tzinfo=kst)
            if start >= end:
                QMessageBox.warning(self, "기간 확인", "시작일은 종료일보다 늦을 수 없습니다.")
                return
        self.controller.scan(list(dict.fromkeys(sources)), start=start, end=end,
                             limit=None if self.all_history.isChecked() else self.limit.value(), topic_id=self.topic.value() or None)

    def save_filter(self, *_):
        if not hasattr(self, "extra_ext"):
            return
        try:
            selection = FileFilter([k for k, cb in self.filter_checks.items() if cb.isChecked()], extensions(self.extra_ext.text()))
            self.store.set_setting("filter", asdict(selection))
            self.controller.generation += 1
            # Update current rows immediately; the background snapshot also stays consistent.
            classifier = self.controller.classifier()
            self.preview_model.classifier = classifier
            for row in self.preview_model.rows:
                row["plan"] = classifier.classify(row["name"], row["manual_id"])
            if self.preview_model.rows:
                self.preview_model.dataChanged.emit(self.preview_model.index(0, 0), self.preview_model.index(len(self.preview_model.rows) - 1, 10))
            self.update_counts()
        except ValueError as error:
            QMessageBox.warning(self, "확장자 확인", str(error))

    def select_formats(self, selected):
        for cb in self.filter_checks.values():
            cb.blockSignals(True)
            cb.setChecked(selected)
            cb.blockSignals(False)
        if not selected:
            self.extra_ext.clear()
        self.save_filter()

    def save_manual(self, key, category_id):
        self.store.update(key, manual_id=category_id)
        self.controller.generation += 1
        self.update_counts()

    def save_selection(self, key, selected):
        self.store.update(key, selected=int(selected))
        self.controller.generation += 1
        self.update_counts()

    def select_files(self, selected):
        keys = []
        for row in range(self.preview_proxy.rowCount()):
            source = self.preview_proxy.mapToSource(self.preview_proxy.index(row, 0)).row()
            item = self.preview_model.rows[source]
            if item["plan"].allowed and item["phase"] not in ACTIVE:
                item["selected"] = int(selected)
                keys.append(item["item_key"])
        self.store.select_many(keys, selected)
        self.controller.generation += 1
        if self.preview_model.rows:
            self.preview_model.dataChanged.emit(self.preview_model.index(0, 0), self.preview_model.index(len(self.preview_model.rows) - 1, 0))
        self.update_counts()

    def download_selected(self):
        plans = [(r["item_key"], r["plan"]) for r in self.preview_model.rows
                 if r["selected"] and r["plan"].allowed and r["phase"] not in ACTIVE]
        if not plans:
            QMessageBox.information(self, "파일 선택", "다운로드할 파일을 체크하세요.")
            return
        self.controller.start_downloads(plans)
        self.tabs.setCurrentIndex(3)

    def save_settings(self):
        try:
            self.store.set_setting("fallback", absolute_folder(self.fallback.text()))
            self.store.set_setting("extra_folders", [absolute_folder(p) for p in self.extra_folders.toPlainText().splitlines() if p.strip()])
            self.store.set_setting("concurrency", self.concurrency.value())
            self.store.set_setting("max_speed_kb", self.speed.value())
            self.rules_changed()
            self.status.setText("설정을 저장했습니다. 진행 중인 다운로드는 시작 시 미리보기 경로를 유지합니다.")
            return True
        except ValueError as error:
            QMessageBox.warning(self, "저장 폴더 확인", str(error))
            return False

    def rules_changed(self):
        self.controller.generation += 1
        self.categories = self.store.categories()
        classifier = self.controller.classifier()
        self.preview_model.classifier = classifier
        for row in self.preview_model.rows:
            row["plan"] = classifier.classify(row["name"], row["manual_id"])
        if self.preview_model.rows:
            self.preview_model.dataChanged.emit(self.preview_model.index(0, 5), self.preview_model.index(len(self.preview_model.rows) - 1, 10))
        self.mark_dirty()

    def start_index(self):
        if self.save_settings():
            self.controller.index()

    def index_done(self, result):
        text = f"{'취소됨' if result['cancelled'] else '인덱싱 완료'}: {result['count']:,}개 / 접근 실패 {len(result['errors']):,}개"
        self.index_result.setText(text + ("\n" + "\n".join(result["errors"][:8]) if result["errors"] else ""))
        self.status.setText(text)

    def mark_dirty(self):
        self.dirty = True

    def refresh_if_dirty(self):
        if self.dirty:
            self.dirty = False
            self.controller.refresh()

    def show_snapshot(self, snapshot):
        if snapshot.get("generation") != self.controller.generation:
            self.mark_dirty()
            return
        self._snapshot = snapshot
        self.categories = snapshot["categories"]
        classifier = self.controller.classifier()
        self.preview_model.replace(snapshot["preview"], classifier)
        self.queue_model.replace(snapshot["queue"], classifier)
        self.update_counts()

    def update_counts(self):
        rows = self.preview_model.rows
        selected = sum(bool(r["selected"] and r["plan"].allowed) for r in rows)
        self.count_label.setText(f"전체 {len(rows):,}개 · 체크한 다운로드 대상 {selected:,}개 (검색으로 숨겨진 체크도 포함)")
        queue = self.queue_model.rows
        completed = sum(r["phase"] in TERMINAL for r in queue)
        failed = sum(r["phase"] == "failed" for r in queue)
        batch = [r for r in queue if r["item_key"] in self.controller.batch_keys] if self.controller.batch_keys else queue
        self.total_progress.setFormat(("이번 작업 " if self.controller.batch_keys else "전체 이력 ") + "%v / %m개 처리 (%p%)")
        self.total_progress.setRange(0, max(1, len(batch)))
        self.total_progress.setValue(sum(r["phase"] in TERMINAL or r["phase"] == "failed" for r in batch))
        self.queue_count.setText(f"전체 {len(queue):,}개 · 완료/중복 {completed:,}개 · 실패 {failed:,}개")

    def activity_changed(self, kind, active):
        if kind == "dialogs":
            self.dialogs_button.setEnabled(not active)
        elif kind == "scan":
            self.scan_button.setEnabled(not active)
            self.scan_progress.setRange(0, 0 if active else 1)
            self.scan_progress.setValue(0 if active else 1)
            if not active:
                self.tabs.setCurrentIndex(1)
        elif kind == "download":
            self.download_button.setEnabled(not active)
        elif kind == "index":
            self.index_button.setEnabled(not active)

    def open_folder(self, *_):
        index = self.queue_table.currentIndex()
        if not index.isValid():
            return
        item = self.queue_model.rows[self.queue_proxy.mapToSource(index).row()]
        folder = str(Path(item["final_path"]).parent) if item["final_path"] else item["folder"]
        if folder and Path(folder).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def shutdown(self):
        self.refresh_timer.stop()
        self.controller.shutdown()
