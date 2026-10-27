import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from smart import local
from smart.local import LocalStore, LocalFileEngine, scan_local
from smart.rules import Category, Classifier, FileFilter


def setup_files(tmp_path, files):
    source, output = tmp_path / "내보낸 원본", tmp_path / "분류 결과 & 보관"
    source.mkdir()
    for name, content in files.items():
        p = source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    store = LocalStore(tmp_path / "state.db")
    store.set_setting("fallback", str(output))
    scan_local(store, [str(source)])
    classifier = Classifier([], str(output), FileFilter([], ["pdf"]))
    plans = [(r["item_key"], classifier.classify(r["name"])) for r in store.local_items()]
    return store, source, output, plans


def test_offline_copy_keyword_manual_and_global_duplicates(tmp_path):
    store, source, output, _ = setup_files(tmp_path, {"CIRCUIT_회로.pdf": b"one", "전자기.pdf": b"two", "other.pdf": b"one"})
    categories = [Category("회로", str(output / "회로"), ["circuit"]), Category("수동", str(output / "수동"))]
    store.save_categories(categories)
    classifier = Classifier(categories, str(output / "미분류"))
    plans = []
    for r in store.local_items():
        manual = categories[1].id if r["name"] == "전자기.pdf" else None
        store.update(r["item_key"], manual_id=manual)
        plans.append((r["item_key"], classifier.classify(r["name"], manual)))
    store.enqueue_local(plans)
    LocalFileEngine(store).run()
    rows = store.local_items()
    assert len(list(source.glob("*.pdf"))) == 3
    assert len(list(output.rglob("*.pdf"))) == 2
    assert sorted(r["phase"] for r in rows) == ["completed", "completed", "duplicate"]
    manual = next(r for r in rows if r["name"] == "전자기.pdf")
    assert Path(manual["final_path"]).parent == output / "수동"


def test_duplicate_existing_other_folder_skips_copy_and_keeps_source(tmp_path, monkeypatch):
    store, source, output, plans = setup_files(tmp_path, {"new.pdf": b"shared"})
    existing = tmp_path / "기존 보관" / "different.pdf"
    existing.parent.mkdir()
    existing.write_bytes(b"shared")
    store.index_folders([str(existing.parent)])
    store.enqueue_local(plans)
    monkeypatch.setattr(LocalFileEngine, "copy_resumable", lambda *args: pytest.fail("duplicate must not be copied"))
    LocalFileEngine(store).run()
    row = store.local_items()[0]
    assert row["phase"] == "duplicate" and Path(row["final_path"]) == existing
    assert (source / "new.pdf").exists()
    assert not list(output.rglob("*.pdf"))


def test_indexed_input_is_never_its_own_output_duplicate(tmp_path):
    store, source, output, plans = setup_files(tmp_path, {"one.pdf": b"data", "two.pdf": b"data"})
    store.index_folders([str(source)])
    store.enqueue_local(plans)
    LocalFileEngine(store).run()
    rows = store.local_items()
    assert len(list(output.glob("*.pdf"))) == 1
    assert all(Path(r["final_path"]).is_relative_to(output) for r in rows)


def test_same_name_different_bytes_and_empty_destination_are_preserved(tmp_path):
    store, source, output, plans = setup_files(tmp_path, {"a/회로.pdf": b"one", "b/회로.pdf": b"two"})
    output.mkdir()
    (output / "회로.pdf").write_bytes(b"")
    store.enqueue_local(plans)
    LocalFileEngine(store).run()
    assert sorted(p.read_bytes() for p in output.glob("*.pdf")) == [b"", b"one", b"two"]
    assert len(list(source.rglob("*.pdf"))) == 2


@pytest.mark.parametrize("cross_volume", [False, True])
def test_explicit_move_is_verified_and_removes_only_successful_source(tmp_path, monkeypatch, cross_volume):
    store, source, output, plans = setup_files(tmp_path, {"move.pdf": b"move safely"})
    if cross_volume:
        monkeypatch.setattr(local, "same_volume", lambda *args: False)
    else:
        monkeypatch.setattr(LocalFileEngine, "copy_resumable", lambda *args: pytest.fail("same-volume move must not copy"))
    store.enqueue_local(plans, "move")
    LocalFileEngine(store).run()
    row = store.local_items()[0]
    assert row["phase"] == "completed"
    assert Path(row["final_path"]).read_bytes() == b"move safely"
    assert not (source / "move.pdf").exists()


def test_duplicate_move_retains_original(tmp_path):
    store, source, output, plans = setup_files(tmp_path, {"one.pdf": b"same", "two.pdf": b"same"})
    store.enqueue_local(plans, "move")
    LocalFileEngine(store).run()
    assert len(list(source.glob("*.pdf"))) == 1
    assert len(list(output.glob("*.pdf"))) == 1
    assert sorted(r["phase"] for r in store.local_items()) == ["completed", "duplicate"]


@pytest.mark.parametrize("change", ["modify", "remove"])
def test_changed_source_after_preview_is_not_processed(tmp_path, change):
    store, source, output, plans = setup_files(tmp_path, {"one.pdf": b"original"})
    p = source / "one.pdf"
    p.write_bytes(b"new content") if change == "modify" else p.unlink()
    store.enqueue_local(plans, "move")
    LocalFileEngine(store).run()
    assert store.local_items()[0]["phase"] == "failed"
    assert not output.exists()
    if change == "modify":
        assert p.read_bytes() == b"new content"


def test_overlapping_source_and_destination_is_rejected(tmp_path):
    store, source, output, _ = setup_files(tmp_path, {"one.pdf": b"original"})
    row = store.local_items()[0]
    store.enqueue_local([(row["item_key"], Classifier([], str(source / "nested")).classify(row["name"]))], "move")
    LocalFileEngine(store).run()
    assert store.local_items()[0]["phase"] == "failed"
    assert (source / "one.pdf").read_bytes() == b"original"
    assert not (source / "nested").exists()


def test_no_space_fails_without_changing_input(tmp_path, monkeypatch):
    store, source, output, plans = setup_files(tmp_path, {"one.pdf": b"original"})
    monkeypatch.setattr(local.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    store.enqueue_local(plans)
    LocalFileEngine(store).run()
    assert store.local_items()[0]["phase"] == "failed"
    assert (source / "one.pdf").read_bytes() == b"original"
    assert not list(output.glob("*.pdf"))


def test_scan_skips_partials_recurses_and_restores_selection(tmp_path):
    store, source, output, plans = setup_files(tmp_path, {"one.pdf": b"x", "sub/two.pdf": b"y", "busy.pdf.part": b"z"})
    assert len(store.local_items()) == 2
    row = store.local_items()[0]
    store.update(row["item_key"], selected=0, manual_id="manual-rule")
    scan_local(store, [str(source), str(source)], recursive=False)
    latest = store.local_items(scan_id=store.setting("local_active_scan"))
    assert [r["name"] for r in latest] == ["one.pdf"]
    assert latest[0]["selected"] == 0 and latest[0]["manual_id"] == "manual-rule"
    restored = LocalStore(store.path)
    assert restored.local_items()[0]["selected"] == 0


def test_scan_cancellation_preserves_partial_batch(tmp_path):
    store, source, output, _ = setup_files(tmp_path, {f"{i}.pdf": b"x" for i in range(250)})
    cancel = threading.Event()
    report = scan_local(store, [str(source)], cancel, lambda *args: cancel.set())
    assert report["cancelled"] and report["count"] == 200
    assert len(store.local_items(scan_id=report["scan_id"])) == 200


def test_pause_restart_and_corrupted_partial_repair(tmp_path, monkeypatch):
    content = b"A" * local.CHUNK + b"B" * local.CHUNK + b"C" * local.CHUNK
    store, source, output, plans = setup_files(tmp_path, {"large.pdf": content})
    cancel = threading.Event()
    ticks = iter(i * .3 for i in range(10000))
    monkeypatch.setattr(local.time, "monotonic", lambda: next(ticks))
    def progress(key, current, total, text):
        if current >= local.CHUNK and "MB/s" in text:
            cancel.set()
    store.enqueue_local(plans)
    LocalFileEngine(store, cancel, progress).run()
    item = store.local_items()[0]
    assert item["phase"] == "paused"
    partial = store.stage(item).with_name("payload.local.part")
    assert partial.exists()
    with partial.open("r+b") as stream:
        stream.write(b"X")
    restored = LocalStore(store.path)
    restored.recover()
    restored.update(item["item_key"], phase="queued")
    LocalFileEngine(restored).run()
    result = restored.local_items()[0]
    assert result["phase"] == "completed"
    assert Path(result["final_path"]).read_bytes() == content
    assert (source / "large.pdf").read_bytes() == content


def test_crash_after_move_publication_recovers_without_losing_file(tmp_path, monkeypatch):
    store, source, output, plans = setup_files(tmp_path, {"one.pdf": b"preserved"})
    store.enqueue_local(plans, "move")
    def crash(*args, **kwargs):
        raise SystemExit("simulated abrupt exit")
    monkeypatch.setattr(store, "_catalog", crash)
    with pytest.raises(SystemExit):
        LocalFileEngine(store).run()
    row = store.local_items()[0]
    assert row["phase"] == "committing"
    restored = LocalStore(store.path)
    restored.recover()
    row = restored.local_items()[0]
    assert row["phase"] == "completed" and Path(row["final_path"]).read_bytes() == b"preserved"


def test_actual_100_mib_file_copies_without_size_limit(tmp_path):
    store, source, output, _ = setup_files(tmp_path, {})
    p = source / "100MB_회로.pdf"
    with p.open("wb") as stream:
        stream.write(b"%PDF-1.7\n")
        stream.seek(100 * 1024 * 1024 - 1)
        stream.write(b"\0")
    scan_local(store, [str(source)])
    row = store.local_items()[0]
    store.enqueue_local([(row["item_key"], Classifier([], str(output)).classify(row["name"]))])
    LocalFileEngine(store).run()
    result = store.local_items()[0]
    assert result["phase"] == "completed" and Path(result["final_path"]).stat().st_size == 100 * 1024 * 1024
    assert local.hash_file(p) == result["sha256"]


def test_move_detects_input_changed_while_comparing_existing_files(tmp_path, monkeypatch):
    store, source, output, plans = setup_files(tmp_path, {"one.pdf": b"original"})
    def changed_during_comparison(*args, **kwargs):
        (source / "one.pdf").write_bytes(b"changed since hashing")
        return None
    monkeypatch.setattr(store, "find_content_duplicate", changed_during_comparison)
    store.enqueue_local(plans, "move")
    LocalFileEngine(store).run()
    assert store.local_items()[0]["phase"] == "failed"
    assert (source / "one.pdf").read_bytes() == b"changed since hashing"
    assert not list(output.glob("*.pdf"))
