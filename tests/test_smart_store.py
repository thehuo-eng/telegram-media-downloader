from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sqlite3
import threading

import pytest

from smart.rules import Category, Classifier
from smart.store import SmartStore, file_key, hash_file


def prepare(store, folder, name="회로.pdf", content=b"original", chat="-1001", mid=1, account="7", file_id=None):
    file_id = file_id or f"document:{chat}:{mid}"
    item = dict(account=account, chat=chat, message_id=mid, slot=0, file_id=file_id, name=name, size=len(content))
    store.upsert_media([item])
    key = file_key(account, chat, mid, 0, file_id)
    store.enqueue([(key, Classifier([], str(folder)).classify(name))])
    row = store.get(key)
    store.stage(row).write_bytes(content)
    return row


def test_migration_preserves_legacy_tables(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE media_cache(msg_id INTEGER,channel_id TEXT,title TEXT)")
        conn.execute("INSERT INTO media_cache VALUES(42,'chat','old file')")
    SmartStore(path)
    SmartStore(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM media_cache").fetchall() == [(42, "chat", "old file")]
        assert conn.execute("SELECT version FROM smart_schema").fetchall() == [(1,)]


def test_account_chat_and_edited_message_identity(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    for account, chat, fid in [("1", "-1001", "a"), ("1", "-1002", "a"), ("2", "-1001", "a"), ("1", "-1001", "edited")]:
        prepare(store, tmp_path / "out", account=account, chat=chat, file_id=fid)
    assert len(store.items()) == 4


@pytest.mark.parametrize("new_name,new_folder", [("same.pdf", "a"), ("renamed.pdf", "a"), ("other.pdf", "b")])
def test_same_content_has_one_copy_regardless_of_name_or_category(tmp_path, new_name, new_folder):
    store = SmartStore(tmp_path / "state.db")
    first = prepare(store, tmp_path / "a", "same.pdf", b"shared")
    path, duplicate = store.finalize(first)
    second = prepare(store, tmp_path / new_folder, new_name, b"shared", mid=2)
    new_path, duplicate = store.finalize(second)
    assert duplicate and new_path == path
    assert store.get(second["item_key"])["sha256"] == hashlib.sha256(b"shared").hexdigest()
    assert not store.stage(second).exists()
    assert Path(path).read_bytes() == b"shared"


def test_same_name_different_content_and_empty_existing_file(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    folder = tmp_path / "한글 경로 & 특수문자"
    folder.mkdir()
    (folder / "same.pdf").write_bytes(b"")
    first = prepare(store, folder, "same.pdf", b"one")
    first_path, _ = store.finalize(first)
    second = prepare(store, folder, "same.pdf", b"two", mid=2)
    second_path, _ = store.finalize(second)
    assert Path(first_path).name == "same (2).pdf"
    assert Path(second_path).name == "same (3).pdf"
    assert (folder / "same.pdf").read_bytes() == b""
    assert Path(first_path).read_bytes() == b"one" and Path(second_path).read_bytes() == b"two"


def test_identical_existing_destination_is_detected_without_index(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    folder = tmp_path / "out"
    folder.mkdir()
    existing = folder / "same.pdf"
    existing.write_bytes(b"shared")
    item = prepare(store, folder, "same.pdf", b"shared")
    path, duplicate = store.finalize(item)
    assert duplicate and Path(path) == existing
    assert not (folder / "same (2).pdf").exists()


def test_index_existing_files_globally_without_deleting_them(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    existing = tmp_path / "managed" / "existing.txt"
    existing.parent.mkdir()
    existing.write_bytes(b"indexed data")
    assert store.index_folders([str(existing.parent)])["count"] == 1
    item = prepare(store, tmp_path / "new category", "different.pdf", b"indexed data")
    path, duplicate = store.finalize(item)
    assert duplicate and Path(path) == existing
    assert existing.read_bytes() == b"indexed data"


def test_restart_manual_settings_and_classified_history(tmp_path):
    db = tmp_path / "state.db"
    store = SmartStore(db)
    category = Category("회로", str(tmp_path / "분류 완료"), ["회로", "circuit"])
    store.save_categories([category])
    store.set_setting("filter", {"groups": ["문서"], "extra_extensions": ["dwg"]})
    item = prepare(store, Path(category.folder), file_id="document:123")
    store.update(item["item_key"], manual_id=category.id)
    path, _ = store.finalize(item)
    restarted = SmartStore(db)
    restarted.recover()
    assert restarted.categories()[0] == category
    assert restarted.setting("filter")["extra_extensions"] == ["dwg"]
    saved = restarted.get(item["item_key"])
    assert saved["manual_id"] == category.id and saved["final_path"] == path
    same = dict(saved, chat="-1002", message_id=99)
    assert restarted.verified_telegram_duplicate(same)["final_path"] == path


def test_missing_or_changed_file_not_silently_skipped(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    item = prepare(store, tmp_path / "out")
    path, _ = store.finalize(item)
    Path(path).write_bytes(b"modified")
    assert store.verified_telegram_duplicate(item) is None
    Path(path).rename(Path(path).with_name("moved.pdf"))
    assert store.verified_telegram_duplicate(item) is None


def test_concurrent_finalizers_do_not_duplicate_content(tmp_path):
    db = tmp_path / "state.db"
    store = SmartStore(db)
    items = [prepare(store, tmp_path / f"category{i}", mid=i) for i in range(8)]
    def finalize(item):
        return SmartStore(db).finalize(item)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(finalize, items))
    assert len({p for p, dup in results}) == 1
    assert sum(not dup for p, dup in results) == 1


def test_crash_between_publication_and_catalog_is_recoverable(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    store = SmartStore(db)
    item = prepare(store, tmp_path / "out")
    def crash(*args):
        raise OSError("simulated process exit after rename")
    monkeypatch.setattr(store, "_catalog", crash)
    with pytest.raises(OSError):
        store.finalize(item)
    assert store.get(item["item_key"])["phase"] == "committing"
    restarted = SmartStore(db)
    restarted.recover()
    restored = restarted.get(item["item_key"])
    assert restored["phase"] == "completed"
    assert Path(restored["final_path"]).read_bytes() == b"original"


def test_partial_is_never_marked_complete(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    item = prepare(store, tmp_path / "out")
    store.stage(item).write_bytes(b"short")
    with pytest.raises(OSError):
        store.finalize(item)
    assert store.get(item["item_key"])["phase"] != "completed"
    store.update(item["item_key"], phase="downloading")
    store.recover()
    assert store.get(item["item_key"])["phase"] == "paused"


def test_cancel_index_and_streaming_hash(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    folder = tmp_path / "managed"
    folder.mkdir()
    target = folder / "large.bin"
    target.write_bytes(b"x" * (3 * 1024 * 1024))
    cancel = threading.Event()
    cancel.set()
    assert store.index_folders([str(folder)], cancel)["cancelled"]
    with pytest.raises(InterruptedError):
        hash_file(target, cancel)
    assert hash_file(target) == hashlib.sha256(target.read_bytes()).hexdigest()


def test_category_validation_has_one_default_and_absolute_paths(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    with pytest.raises(ValueError):
        store.save_categories([Category("relative", "../unsafe")])
    with pytest.raises(ValueError):
        store.save_categories([Category("a", str(tmp_path), is_default=True), Category("b", str(tmp_path), is_default=True)])
