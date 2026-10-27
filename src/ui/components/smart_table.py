from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate

from smart.rules import Classifier, extension, normalized, safe_filename
from smart.store import ACTIVE, TERMINAL

PHASES = {"discovered": "다운로드 가능", "queued": "대기", "downloading": "다운로드 중", "paused": "일시정지",
          "verifying": "SHA-256 검사 중", "committing": "최종 저장 중", "completed": "완료", "duplicate": "중복 사본 생략", "failed": "실패"}


def file_size(size):
    if size < 0:
        return "미확인"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}" if unit != "B" else f"{size:,} B"
        size /= 1024


class MediaTableModel(QAbstractTableModel):
    manual_changed = Signal(str, object)
    selection_changed = Signal(str, bool)
    HEADERS = ["선택", "원본 파일명", "채팅방", "확장자", "크기", "범주", "적용 규칙 / 충돌", "최종 저장 폴더", "중복 확인", "예상 / 현재 상태", "최종 파일명 / 경로"]

    def __init__(self, queue=False, parent=None, local=False):
        super().__init__(parent)
        self.rows, self.by_key = [], {}
        self.queue = queue
        self.local = local
        if local:
            self.HEADERS = list(self.HEADERS)
            self.HEADERS[2] = "원본 폴더"
        self.classifier = None
        self.progress = {}

    def replace(self, rows, classifier):
        self.beginResetModel()
        self.rows = rows
        self.classifier = classifier
        self.by_key = {r["item_key"]: i for i, r in enumerate(rows)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return self.HEADERS[section] if orientation == Qt.Horizontal else section + 1

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item, col = self.rows[index.row()], index.column()
        plan = item["plan"]
        if role == Qt.CheckStateRole and col == 0:
            return Qt.Checked if item["selected"] and plan.allowed else Qt.Unchecked
        if role == Qt.EditRole and col == 5:
            return item["manual_id"]
        if role == Qt.ForegroundRole and not plan.allowed and not self.queue:
            return QColor("#888888")
        if role == Qt.UserRole:
            return item["size"] if col == 4 else normalized(self.data(index) or "")
        if role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        category = item["category"] if self.queue else plan.category
        folder = item["folder"] if self.queue else plan.folder
        rule = item["rule"] if self.queue else plan.rule
        if not self.queue and plan.conflicts:
            rule += " | 충돌: " + ", ".join(plan.conflicts)
        status = PHASES.get(item["phase"], item["phase"])
        if self.local:
            status = {"discovered": "분류 가능", "downloading": "복사 중", "duplicate": "중복 — 원본 유지"}.get(item["phase"], status)
        if not self.queue and not plan.allowed:
            status = "형식 필터로 제외"
        elif item["phase"] == "downloading" and item["item_key"] in self.progress:
            current, total, speed = self.progress[item["item_key"]]
            status = f"{current / total * 100:.1f}% · {speed}" if total > 0 else f"{file_size(current)} · {speed}"
        if item["error"]:
            status += " — " + item["error"]
        final = item["final_path"] if self.queue else str(Path(folder) / safe_filename(item["name"])) if folder else ""
        values = ["", item["name"], item["chat_title"], extension(item["name"]) or "없음", file_size(item["size"]),
                  category or "미분류", rule or "", folder or "", item["duplicate_hint"], status, final or ""]
        if self.queue and item["phase"] in TERMINAL:
            values[8] = "SHA-256 검사 완료" if item["sha256"] else "내용 미확인"
        return values[col]

    def flags(self, index):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.isValid() and not self.queue:
            item = self.rows[index.row()]
            if index.column() == 0 and item["plan"].allowed and item["phase"] not in ACTIVE:
                flags |= Qt.ItemIsUserCheckable
            if index.column() == 5 and item["phase"] not in ACTIVE:
                flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or self.queue:
            return False
        item = self.rows[index.row()]
        if item["phase"] in ACTIVE:
            return False
        if index.column() == 0 and role == Qt.CheckStateRole:
            item["selected"] = value == Qt.Checked or value == Qt.Checked.value
            self.selection_changed.emit(item["item_key"], item["selected"])
        elif index.column() == 5 and role == Qt.EditRole:
            item["manual_id"] = value or None
            item["plan"] = self.classifier.classify(item["name"], item["manual_id"])
            self.manual_changed.emit(item["item_key"], item["manual_id"])
        else:
            return False
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), self.columnCount() - 1))
        return True

    def set_progress(self, key, current, total, speed):
        self.progress[key] = (current, total, speed)
        if key in self.by_key:
            index = self.index(self.by_key[key], 9)
            self.dataChanged.emit(index, index)


class MediaProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.phases = None
        self.setSortRole(Qt.UserRole)

    def search(self, text):
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
        self.query = normalized(text)
        self._finish_filter_change()

    def set_phases(self, phases):
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
        self.phases = phases
        self._finish_filter_change()

    def _finish_filter_change(self):
        if hasattr(self, "endFilterChange"):
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        item = self.sourceModel().rows[source_row]
        return (not self.phases or item["phase"] in self.phases) and (
            not self.query or self.query in normalized(item["name"] + " " + item["chat_title"]))


class CategoryDelegate(QStyledItemDelegate):
    def __init__(self, categories, parent=None):
        super().__init__(parent)
        self.categories = categories

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItem("자동 분류로 되돌리기", None)
        for cat in self.categories():
            editor.addItem(cat.name, cat.id)
        return editor

    def setEditorData(self, editor, index):
        editor.setCurrentIndex(max(0, editor.findData(index.data(Qt.EditRole))))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentData(), Qt.EditRole)
