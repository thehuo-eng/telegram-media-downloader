"""All automated tests use synthetic local data and never load user sessions."""
import os
import tempfile

_data = tempfile.TemporaryDirectory(prefix="telegram-smart-tests-")
os.environ.setdefault("TSD_DATA_DIR", _data.name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
