import sys
import os
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

# Keep a global reference to the app to update styles later
_app_instance = None


def is_system_dark_mode() -> bool:
    """Detect the OS dark mode preference. Works on Windows, macOS, and Linux."""
    import platform
    system = platform.system()

    if system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return value == 0  # 0 = dark mode, 1 = light mode
        except Exception:
            return False

    elif system == "Darwin":  # macOS
        try:
            import subprocess
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2
            )
            return result.stdout.strip().lower() == "dark"
        except Exception:
            return False

    else:  # Linux / other
        try:
            # Check GTK theme (works with GNOME, KDE Breeze-Dark, etc.)
            import subprocess
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                capture_output=True, text=True, timeout=2
            )
            return "dark" in result.stdout.strip().lower()
        except Exception:
            pass
        # Fallback: check XDG_CURRENT_DESKTOP / GTK_THEME env vars
        import os as _os
        gtk_theme = _os.environ.get("GTK_THEME", "").lower()
        return "dark" in gtk_theme


from resource_utils import get_resource_path


def apply_theme(is_dark=False):
    global _app_instance
    if not _app_instance:
        return

    # Persist the preference to config
    try:
        from ui.views.settings_view import load_config, save_config
        cfg = load_config()
        cfg["dark_mode"] = is_dark
        save_config(cfg)
    except Exception:
        pass

    filename = "dark_style.qss" if is_dark else "style.qss"
    qss_path = get_resource_path(os.path.join("assets", "styles", filename))
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            from ui.smart_theme import stylesheet
            _app_instance.setStyleSheet(f.read() + stylesheet(is_dark))


def launch_app(telegram_worker, version="unknown"):
    global _app_instance
    _app_instance = QApplication(sys.argv)
    # One process per data directory protects queue and staging ownership.
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QMessageBox
    from resource_utils import get_project_root
    instance_lock = QLockFile(os.path.join(get_project_root(), 'smart-downloader.lock'))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(0):
        QMessageBox.information(None, "이미 실행 중", "같은 데이터 폴더의 프로그램이 이미 실행 중입니다.")
        return

    from PySide6.QtGui import QIcon, QFont
    if "--smoke-test" in sys.argv and os.name == "nt":
        from PySide6.QtGui import QFontDatabase
        for name in ('malgun.ttf', 'malgunbd.ttf', 'segoeui.ttf'):
            path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', name)
            if os.path.isfile(path):
                QFontDatabase.addApplicationFont(path)
    _app_instance.setFont(QFont("Malgun Gothic" if os.name == "nt" else "Sans Serif", 9))

    icon_path = get_resource_path(os.path.join("assets", "logo.ico"))
    if os.path.exists(icon_path):
        _app_instance.setWindowIcon(QIcon(icon_path))

    # Determine startup theme:
    #   1. Use saved preference from config.json (if explicitly set by user)
    #   2. Fall back to Windows system dark mode detection
    try:
        from ui.views.settings_view import load_config
        cfg = load_config()
        saved_pref = cfg.get("dark_mode", None)
    except Exception:
        saved_pref = None

    if saved_pref is not None:
        startup_dark = bool(saved_pref)
    else:
        startup_dark = is_system_dark_mode()

    apply_theme(is_dark=startup_dark)

    window = MainWindow(telegram_worker, version)
    window.show()

    # Start the worker thread
    if "--smoke-test" in sys.argv:
        from PySide6.QtCore import QTimer
        from smart.smoke import finish_smoke
        QTimer.singleShot(1200, lambda: finish_smoke(window, _app_instance))
    else:
        telegram_worker.start()

    exit_code = _app_instance.exec()
    
    # Ensure worker stops before the thread object is destroyed by GC
    if telegram_worker.isRunning():
        telegram_worker.stop()
        # Increased wait time for clean asyncio shutdown
        if not telegram_worker.wait(3000):
            # If it still won't stop, we force quit it (less clean but avoids the error)
            telegram_worker.terminate()
            telegram_worker.wait()

    sys.exit(exit_code)

