import time

import pytest
from PySide6.QtCore import Qt, QTimer, QObject, Signal
from PySide6.QtWidgets import QApplication

from smart.rules import Category, Classifier
from smart.store import SmartStore
from ui.components.smart_table import MediaTableModel, MediaProxy
from ui.views.smart_view import SmartView


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app


class Signals(QObject):
    auth_success = Signal()
    auth_needed = Signal()


class Worker:
    def __init__(self):
        self.signals = Signals()
        self.loop = None


def row(i, classifier):
    name = f"회로_{i:05}.pdf"
    return dict(item_key=str(i), name=name, size=i + 100, account="7", file_id=f"document:{i}",
                chat="-1001", chat_title="테스트 채팅", manual_id=None, selected=1, phase="discovered",
                plan=classifier.classify(name), duplicate_hint="내용 미확인", error="", final_path=None,
                category=None, folder=None, rule=None)


def test_manual_category_immediately_updates_preview_path(app, tmp_path):
    cats = [Category("회로", str(tmp_path / "회로"), ["회로"]), Category("수동 범주", str(tmp_path / "수동"))]
    classifier = Classifier(cats, str(tmp_path / "미분류"))
    model = MediaTableModel()
    model.replace([row(1, classifier)], classifier)
    emitted = []
    model.manual_changed.connect(lambda key, cat: emitted.append((key, cat)))
    assert model.setData(model.index(0, 5), cats[1].id)
    assert model.data(model.index(0, 5)) == "수동 범주"
    assert model.data(model.index(0, 7)) == str(tmp_path / "수동")
    assert emitted == [("1", cats[1].id)]


def test_large_list_uses_model_and_event_loop_remains_responsive(app, tmp_path):
    classifier = Classifier([Category("회로", str(tmp_path), ["회로"])], str(tmp_path))
    model = MediaTableModel()
    rows = [row(i, classifier) for i in range(25000)]
    started = time.monotonic()
    model.replace(rows, classifier)
    proxy = MediaProxy()
    proxy.setSourceModel(model)
    proxy.search("회로_24999")
    assert proxy.rowCount() == 1
    assert time.monotonic() - started < 3.0
    beats = []
    QTimer.singleShot(0, lambda: beats.append(True))
    app.processEvents()
    assert beats and model.rowCount() == 25000


def test_smart_gui_offline_settings_and_filter_round_trip(app, tmp_path):
    view = SmartView(Worker(), tmp_path / "state.db")
    try:
        assert view.tabs.count() == 5
        view.fallback.setText(str(tmp_path / "미분류"))
        view.speed.setValue(1024)
        assert view.save_settings()
        view.select_formats(False)
        view.extra_ext.setText("pdf, hwpx")
        view.save_filter()
        restored = SmartStore(tmp_path / "state.db")
        assert restored.setting("max_speed_kb") == 1024
        assert restored.setting("filter") == {"groups": [], "extra_extensions": ["pdf", "hwpx"]}
    finally:
        view.shutdown()
        view.close()
