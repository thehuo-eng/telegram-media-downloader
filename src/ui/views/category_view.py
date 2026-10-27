import re
from dataclasses import replace

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QLineEdit, QPlainTextEdit,
                               QCheckBox, QPushButton, QFileDialog, QMessageBox, QLabel, QFormLayout,
                               QScrollArea, QSplitter, QSizePolicy)

from smart.rules import Category, Classifier, extensions


class CategoryView(QWidget):
    changed = Signal()

    def __init__(self, store, fallback, parent=None):
        super().__init__(parent)
        self.store, self.fallback = store, fallback
        self.categories = store.categories()
        self.edit_id = None
        root = QVBoxLayout(self)
        hint = QLabel("위에 있는 범주가 우선입니다. 수동 지정 → 키워드 → 확장자 전용 범주 → 기본 범주 / 미분류 순으로 적용합니다.")
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root.addWidget(hint)
        split = QSplitter()
        root.addWidget(split, 1)
        left = QWidget()
        layout = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.load_row)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        for label, action in [("범주 추가", self.new), ("삭제", self.remove), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1))]:
            button = QPushButton(label)
            button.clicked.connect(action)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        split.addWidget(left)
        right = QWidget()
        form = QFormLayout(right)
        self.name = QLineEdit()
        self.keywords = QPlainTextEdit()
        self.keywords.setPlaceholderText("키워드를 줄바꿈 또는 쉼표로 구분\n회로\ncircuit\nch09")
        self.keywords.setMaximumHeight(140)
        self.ext = QLineEdit()
        self.ext.setPlaceholderText("빈칸: 전체 / 예: pdf, mp4, hwpx")
        self.folder = QLineEdit()
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder)
        choose = QPushButton("폴더 선택")
        choose.clicked.connect(self.choose_folder)
        folder_row.addWidget(choose)
        self.enabled = QCheckBox("활성화")
        self.enabled.setChecked(True)
        self.default = QCheckBox("일치 규칙이 없는 파일의 기본 범주")
        for label, widget in [("범주 이름", self.name), ("키워드 (OR 조건)", self.keywords), ("확장자 조건", self.ext)]:
            form.addRow(label, widget)
        form.addRow("최종 저장 폴더", folder_row)
        form.addRow(self.enabled)
        form.addRow(self.default)
        save = QPushButton("범주 변경 저장")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self.save)
        form.addRow(save)
        form.addRow(QLabel("저장된 규칙 테스트"))
        self.test_name = QLineEdit()
        self.test_name.setPlaceholderText("예: CIRCUIT_lecture03.mp4")
        self.test_name.textChanged.connect(self.test_rules)
        form.addRow(self.test_name)
        test = QPushButton("분류 규칙 테스트")
        test.clicked.connect(self.test_rules)
        form.addRow(test)
        self.test_result = QLabel("파일명을 입력하면 분류 결과를 보여줍니다.")
        self.test_result.setWordWrap(True)
        self.test_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.test_result)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(right)
        split.addWidget(area)
        split.setSizes([260, 600])
        self.reload()

    def reload(self):
        self.list.blockSignals(True)
        self.list.clear()
        for i, cat in enumerate(self.categories):
            self.list.addItem(f"{i + 1}. {cat.name}" + (" (비활성)" if not cat.enabled else "") + (" [기본]" if cat.is_default else ""))
        self.list.blockSignals(False)
        self.test_rules()

    def new(self):
        self.edit_id = None
        self.list.setCurrentRow(-1)
        self.name.clear()
        self.keywords.clear()
        self.ext.clear()
        self.folder.setText(self.fallback())
        self.enabled.setChecked(True)
        self.default.setChecked(False)
        self.name.setFocus()

    def load_row(self, row):
        if row < 0 or row >= len(self.categories):
            return
        cat = self.categories[row]
        self.edit_id = cat.id
        self.name.setText(cat.name)
        self.keywords.setPlainText("\n".join(cat.keywords))
        self.ext.setText(", ".join(cat.extensions))
        self.folder.setText(cat.folder)
        self.enabled.setChecked(cat.enabled)
        self.default.setChecked(cat.is_default)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "범주 저장 폴더", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def persist(self, updated):
        try:
            self.store.save_categories(updated)
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "범주 설정 확인", str(error))
            return False
        self.categories = updated
        self.reload()
        self.changed.emit()
        return True

    def save(self):
        try:
            data = dict(name=self.name.text(), folder=self.folder.text(),
                        keywords=[k.strip() for k in re.split(r"[,\n]+", self.keywords.toPlainText()) if k.strip()],
                        extensions=extensions(self.ext.text()), enabled=self.enabled.isChecked(), is_default=self.default.isChecked())
            if self.edit_id:
                data["id"] = self.edit_id
            cat = Category(**data).validate()
            updated = [replace(c) for c in self.categories]
            index = next((i for i, c in enumerate(updated) if c.id == self.edit_id), len(updated))
            if index == len(updated):
                updated.append(cat)
            else:
                updated[index] = cat
            if self.persist(updated):
                self.list.setCurrentRow(index)
        except ValueError as error:
            QMessageBox.warning(self, "범주 설정 확인", str(error))

    def remove(self):
        row = self.list.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, "범주 삭제", "이 범주 설정을 삭제할까요? 저장된 파일과 다운로드 기록은 유지됩니다.",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if self.persist([replace(c) for i, c in enumerate(self.categories) if i != row]):
            self.new()

    def move(self, direction):
        row = self.list.currentRow()
        target = row + direction
        if row < 0 or not 0 <= target < len(self.categories):
            return
        updated = [replace(c) for c in self.categories]
        updated[row], updated[target] = updated[target], updated[row]
        if self.persist(updated):
            self.list.setCurrentRow(target)

    def test_rules(self, *_):
        name = self.test_name.text().strip()
        if not name:
            return
        result = Classifier(self.categories, self.fallback()).classify(name)
        text = f"{result.category} · {result.rule}\n{result.folder}"
        if result.conflicts:
            text += "\n충돌 (우선순위로 결정): " + ", ".join(result.conflicts)
        self.test_result.setText(text)
