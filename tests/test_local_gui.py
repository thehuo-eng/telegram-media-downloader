import time
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from smart.rules import Category
from ui.views.local_view import LocalView


class Signals(QObject):
    auth_success = Signal()
    auth_needed = Signal()


class OfflineWorker:
    def __init__(self):
        self.signals = Signals()
        self.loop = None

    def start(self):
        raise AssertionError("local mode must never connect to Telegram")


def wait_for(app, condition):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        app.processEvents()
        if condition():
            return
        time.sleep(.02)
    raise AssertionError("local GUI operation timed out")


def test_local_gui_end_to_end_without_credentials(tmp_path):
    app = QApplication.instance() or QApplication([])
    view = LocalView(OfflineWorker(), tmp_path / "state.db")
    errors = []
    view.controller.error.disconnect()
    view.controller.error.connect(errors.append)
    source, out = tmp_path / "export", tmp_path / "classified"
    source.mkdir()
    (source / "회로_100.pdf").write_bytes(b"PDF payload")
    (source / "photo.jpg").write_bytes(b"image")
    try:
        assert view.local_mode and view.tabs.count() == 5 and view.tabs.tabText(0) == "1. 원본 폴더"
        assert view.controller.classifier().file_filter.extra_extensions == ["pdf"]
        assert view.operation.currentData() == "copy"
        view.fallback.setText(str(out / "미분류"))
        assert view.save_settings()
        category = Category("회로", str(out / "회로"), ["회로"])
        view.store.save_categories([category])
        view.rules_changed()
        view.source_folders.addItem(str(source))
        view.scan()
        wait_for(app, lambda: not view.controller.scanning and len(view.preview_model.rows) == 2)
        assert sum(r["plan"].allowed for r in view.preview_model.rows) == 1
        view.download_selected()
        wait_for(app, lambda: not view.controller.downloading and (out / "회로" / "회로_100.pdf").exists())
        assert (source / "회로_100.pdf").exists()
        assert not list(out.rglob("*.jpg"))
        assert not errors
    finally:
        view.shutdown()
        view.controller.executor.shutdown(wait=True)
        view.close()


def test_default_application_startup_never_loads_credentials_or_starts_telegram(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ, TSD_DATA_DIR=str(tmp_path / "offline-app"), QT_QPA_PLATFORM="offscreen",
               PYTHONPATH=str(repo / "src"), PYTHONIOENCODING="utf-8")
    code = r'''
import gui
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import ui.app
def blocked(*args, **kwargs):
    raise AssertionError("Offline startup attempted Telegram or credential access")
gui.load_dotenv = blocked
gui.TelegramWorker.start = blocked
gui.TelegramWorker._create_client = blocked
BaseWindow = ui.app.MainWindow
class CheckWindow(BaseWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert self.local_mode and self.page_smart.local_mode
        assert self.btn_logout.isHidden()
        QTimer.singleShot(300, self.finish)
    def finish(self):
        assert self.worker.client is None and not self.worker.isRunning()
        self.close()
        print("OFFLINE_STARTUP_OK")
        QApplication.instance().quit()
ui.app.MainWindow = CheckWindow
gui.main()
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=repo, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=25)
    assert result.returncode == 0, result.stderr[-2500:]
    assert "OFFLINE_STARTUP_OK" in result.stdout
