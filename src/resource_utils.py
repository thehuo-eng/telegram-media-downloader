import os
import sys

def get_resource_path(relative_path: str) -> str:
    """Get the absolute path to a resource, supporting both development and PyInstaller bundles."""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller temporary extraction folder
        return os.path.join(sys._MEIPASS, relative_path)
    
    # Development: Resources are relative to the 'src' directory
    # Assume this file is in 'src/resource_utils.py'
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, relative_path)

def get_project_root() -> str:
    """Get the persistent project root where .env, config.json, and session files should be stored."""
    override = os.environ.get('TSD_DATA_DIR')
    if override:
        os.makedirs(override, exist_ok=True)
        return os.path.abspath(override)
    if getattr(sys, 'frozen', False):
        # Preserve existing portable installations; new installs use a writable user directory.
        portable = os.path.dirname(sys.executable)
        if os.path.exists(os.path.join(portable, 'downloader.db')):
            return portable
        data_dir = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'TelegramSmartDownloader')
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    
    # Development: Root is one level above 'src/'
    # Assuming this file is in 'src/resource_utils.py'
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
