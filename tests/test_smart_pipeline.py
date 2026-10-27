from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest
from telethon.errors import FloodWaitError
from telethon.tl.types import PeerChannel

from smart.pipeline import DownloadEngine, media_records, scan_history
from smart.rules import Category, Classifier
from smart.store import SmartStore, file_key
from utils.fast_telethon import CHUNK_SIZE, GLOBAL_FLOODGATE


def message(mid=1, name="회로.pdf", content=b"test payload", fid=99, date=None):
    doc = SimpleNamespace(id=fid, size=len(content), attributes=[SimpleNamespace(file_name=name)])
    media = SimpleNamespace(document=doc, photo=None)
    return SimpleNamespace(id=mid, date=date or datetime(2026, 1, 2, tzinfo=timezone.utc),
                           media=media, document=doc, photo=None, file=SimpleNamespace(name=name, size=len(content)), content=content)


class Client:
    def __init__(self, messages):
        self.messages = messages
        self.transfers = 0
        self.offsets = []
        self.requests = []
        self.cancel_after_chunk = None
        self.failure = None

    async def get_entity(self, source):
        return PeerChannel(123)

    async def get_input_entity(self, source):
        return source

    async def get_messages(self, entity, ids):
        return next(m for m in self.messages if m.id == ids)

    async def iter_messages(self, entity, **kwargs):
        self.requests.append(kwargs)
        emitted = 0
        for item in sorted(self.messages, key=lambda m: m.id, reverse=True):
            if kwargs.get("offset_id") and item.id >= kwargs["offset_id"]:
                continue
            if kwargs.get("offset_date") and item.date >= kwargs["offset_date"]:
                continue
            if kwargs.get("limit") is not None and emitted >= kwargs["limit"]:
                break
            emitted += 1
            yield item

    async def iter_download(self, target, offset, request_size):
        self.transfers += 1
        self.offsets.append(offset)
        if self.failure:
            raise self.failure
        item = next(m for m in self.messages if m.media.document.id == target.document.id)
        for i in range(offset, len(item.content), CHUNK_SIZE):
            yield item.content[i:i + CHUNK_SIZE]
            if self.cancel_after_chunk:
                self.cancel_after_chunk.set()
                self.cancel_after_chunk = None


def queue(store, folder, messages, account="7", chat="-100123"):
    for item in messages:
        records = media_records(item, account, chat, "테스트 채팅")
        store.upsert_media(records)
        plan = Classifier([], str(folder)).classify(item.file.name)
        store.enqueue([(records[0]["item_key"], plan)])


@pytest.mark.asyncio
async def test_entire_history_exceeds_500_and_supports_topic_and_dates(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    messages = [message(i, fid=i) for i in range(1, 1251)]
    client = Client(messages)
    result = await scan_history(client, store, "7", ["-100123"], threading.Event(), topic_id=42)
    assert result["files"] == 1250 and len(store.items("7")) == 1250
    assert client.requests[0]["limit"] is None and client.requests[0]["reply_to"] == 42
    date = datetime(2026, 1, 2, tzinfo=timezone.utc)
    result = await scan_history(client, store, "7", ["-100123"], threading.Event(), start=date + timedelta(days=1))
    assert result["files"] == 0


@pytest.mark.asyncio
async def test_scan_cancel_keeps_completed_batches(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    cancel = threading.Event()
    result = await scan_history(Client([message(i, fid=i) for i in range(1, 2001)]), store, "7", ["-100123"], cancel,
                                on_batch=lambda count: cancel.set())
    assert result["cancelled"] and len(store.items()) == 200


@pytest.mark.asyncio
async def test_end_to_end_download_preview_folder_and_history_skip(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    item = message(name="CIRCUIT_강의.pdf")
    records = media_records(item, "7", "-100123")
    store.upsert_media(records)
    category = Category("회로", str(tmp_path / "회로"), ["circuit"])
    preview = Classifier([category], str(tmp_path / "미분류")).classify(item.file.name)
    store.enqueue([(records[0]["item_key"], preview)])
    client = Client([item])
    await DownloadEngine(client, store, "7").run()
    saved = store.get(records[0]["item_key"])
    assert saved["phase"] == "completed"
    assert Path(saved["final_path"]).parent == Path(preview.folder)
    assert Path(saved["final_path"]).read_bytes() == item.content
    store.update(saved["item_key"], phase="queued")
    await DownloadEngine(client, SmartStore(store.path), "7").run()
    assert client.transfers == 1 and store.get(saved["item_key"])["phase"] == "duplicate"


@pytest.mark.asyncio
async def test_parallel_same_telegram_file_downloaded_once(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    messages = [message(i) for i in range(1, 6)]
    queue(store, tmp_path / "out", messages)
    client = Client(messages)
    await DownloadEngine(client, store, "7").run(concurrency=5)
    assert client.transfers == 1
    assert sum(r["phase"] == "completed" for r in store.items()) == 1
    assert sum(r["phase"] == "duplicate" for r in store.items()) == 4


@pytest.mark.asyncio
async def test_pause_restart_resume_uses_partial_offset(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    item = message(content=b"A" * CHUNK_SIZE + b"B" * CHUNK_SIZE + b"end")
    queue(store, tmp_path / "out", [item])
    cancel = threading.Event()
    client = Client([item])
    client.cancel_after_chunk = cancel
    await DownloadEngine(client, store, "7", cancel).run()
    row = store.items()[0]
    assert row["phase"] == "paused" and not row["final_path"]
    restarted = SmartStore(store.path)
    restarted.recover()
    restarted.update(row["item_key"], phase="queued")
    await DownloadEngine(client, restarted, "7").run()
    row = restarted.get(row["item_key"])
    assert row["phase"] == "completed"
    assert client.offsets == [0, CHUNK_SIZE]
    assert Path(row["final_path"]).read_bytes() == item.content


@pytest.mark.asyncio
async def test_network_failure_has_bounded_retries(tmp_path, monkeypatch):
    async def no_delay(seconds, cancel):
        pass
    monkeypatch.setattr("smart.pipeline.cancellable_wait", no_delay)
    store = SmartStore(tmp_path / "state.db")
    item = message()
    queue(store, tmp_path / "out", [item])
    client = Client([item])
    client.failure = OSError("simulated network outage")
    await DownloadEngine(client, store, "7").run()
    assert client.transfers == 3
    assert store.items()[0]["phase"] == "failed"


@pytest.mark.asyncio
async def test_flood_wait_is_fully_observed(tmp_path, monkeypatch):
    waits = []
    async def record_wait(seconds, cancel):
        waits.append(seconds)
    monkeypatch.setattr("smart.pipeline.cancellable_wait", record_wait)
    async def allow_fake_gate(cancel=None):
        return True
    monkeypatch.setattr(GLOBAL_FLOODGATE, "acquire", allow_fake_gate)
    store = SmartStore(tmp_path / "state.db")
    item = message()
    queue(store, tmp_path / "out", [item])
    client = Client([item])
    client.failure = FloodWaitError(request=None, capture=17)
    try:
        await DownloadEngine(client, store, "7").run()
        assert waits == [17, 17, 17]
        assert store.items()[0]["phase"] == "failed"
    finally:
        GLOBAL_FLOODGATE.reset()


@pytest.mark.asyncio
async def test_changed_remote_document_does_not_overwrite_history(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    original = message(fid=1)
    queue(store, tmp_path / "out", [original])
    client = Client([message(fid=2)])
    await DownloadEngine(client, store, "7").run()
    assert client.transfers == 0
    assert store.items()[0]["phase"] == "failed"


@pytest.mark.asyncio
async def test_missing_local_completed_file_can_be_downloaded_again(tmp_path):
    store = SmartStore(tmp_path / "state.db")
    item = message()
    queue(store, tmp_path / "out", [item])
    client = Client([item])
    await DownloadEngine(client, store, "7").run()
    saved = store.items()[0]
    Path(saved["final_path"]).rename(tmp_path / "user-moved.pdf")
    store.update(saved["item_key"], phase="queued")
    await DownloadEngine(client, store, "7").run()
    assert client.transfers == 2
    assert store.get(saved["item_key"])["phase"] == "completed"
