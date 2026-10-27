"""Render synthetic GUI examples without opening a Telegram session.

Run: python tools/qa_preview.py --output .test-data/visual-qa
"""
import argparse
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
args = parser.parse_args()
root = Path(args.output).resolve()
root.mkdir(parents=True, exist_ok=True)
os.environ["TSD_DATA_DIR"] = str(root / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtCore import QTimer
from workers.telegram_worker import TelegramWorker
from ui.main_window import MainWindow
from smart.rules import Category
from smart.local import scan_local
from smart import VERSION
import ui.app

app = QApplication([])
ui.app._app_instance = app
if os.name == "nt":
    for name in ("malgun.ttf", "malgunbd.ttf", "segoeui.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
app.setFont(QFont("Malgun Gothic", 9))
ui.app.apply_theme(True)
worker = TelegramWorker("offline-qa", 0, "")
window = MainWindow(worker, VERSION)
window.resize(1280, 800)
store = window.page_smart.store
store.save_categories([
    Category("회로이론", str(root / "공부자료" / "회로이론"), ["회로", "circuit", "ch09"]),
    Category("전자기학", str(root / "공부자료" / "전자기학"), ["전자기학", "ampere", "회로"], priority=1),
    Category("강의영상", str(root / "강의영상"), extensions=["mp4", "mkv", "avi"], priority=2),
])
names = ["회로이론_9장.pdf", "CIRCUIT_lecture03.mp4", "전자기학_기출2025.pdf", "일반_강의영상.mkv", "수업자료.zip", "README"]
source = root / "내보낸 원본 (가상 예시)"
source.mkdir(exist_ok=True)
for i, name in enumerate(names, 1):
    (source / name).write_bytes(bytes([i]) * ((i + 1) * 1024))
scan_local(store, [str(source)])
store.set_setting("fallback", str(root / "미분류"))
view = window.page_smart
view.source_folders.addItem(str(source))
view.category_view.categories = store.categories()
view.category_view.reload()
view.category_view.list.setCurrentRow(0)
view.category_view.test_name.setText("CIRCUIT_lecture03.mp4")
view.controller.refresh()
window.show()

def capture():
    for index, name in [(0, "sources"), (1, "preview"), (2, "categories"), (4, "settings")]:
        view.tabs.setCurrentIndex(index)
        app.processEvents()
        window.grab().save(str(root / f"smart-{name}.png"))
    ui.app.apply_theme(False)
    view.tabs.setCurrentIndex(1)
    app.processEvents()
    window.grab().save(str(root / "smart-preview-light.png"))
    window.close()
    app.quit()

QTimer.singleShot(1500, capture)
app.exec()
