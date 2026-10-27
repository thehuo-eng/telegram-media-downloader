"""Offline packaged-application smoke check; never starts a Telegram client."""
import json
from pathlib import Path

from resource_utils import get_project_root


def finish_smoke(window, app):
    root = Path(get_project_root())
    result = {"window_created": window.isVisible(), "smart_tabs": window.page_smart.tabs.count(),
              "version": window.version, "telegram_started": window.worker.isRunning(),
              "local_mode": window.local_mode, "folder_picker": hasattr(window.page_smart, "source_folders")}
    window.grab().save(str(root / "smoke-window.png"))
    (root / "smoke-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    window.close()
    app.quit()
