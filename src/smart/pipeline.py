"""Telegram metadata scanning and verified downloads on the existing asyncio worker."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
import time

from telethon.errors import FloodWaitError, FileReferenceExpiredError
from telethon.tl.types import MessageMediaPaidMedia, MessageExtendedMedia
from telethon.utils import get_peer_id

from core_downloader import parse_channel_input, fetch_channel
from smart.store import SmartStore, file_key
from utils.fast_telethon import fast_download_file, GLOBAL_FLOODGATE, CHUNK_SIZE
from utils.file_utils import get_media_filename


def media_records(message, account, chat, title="", source=""):
    """Store metadata, never authentication, file references or full message bodies."""
    media = getattr(message, "media", None)
    if not media:
        return []
    if isinstance(media, MessageMediaPaidMedia):
        targets = [(i, x.media) for i, x in enumerate(media.extended_media)
                   if isinstance(x, MessageExtendedMedia)]
    else:
        targets = [(0, media)]
    records = []
    for slot, target in targets:
        doc, photo = getattr(target, "document", None), getattr(target, "photo", None)
        if not doc and not photo:
            continue
        obj = doc or photo
        kind = "document" if doc else "photo"
        filename = None
        for attr in getattr(doc, "attributes", ()):
            if getattr(attr, "file_name", None):
                filename = attr.file_name
                break
        # Retain the actual Telegram filename for matching and display.
        if not filename and not isinstance(media, MessageMediaPaidMedia):
            filename = getattr(getattr(message, "file", None), "name", None)
        filename = filename or get_media_filename(message, prefix_date=False, prefix_channel=False,
                                                  target_media=target, sub_index=slot + 1 if len(targets) > 1 else None)
        if doc:
            size = int(doc.size)
        else:
            sizes = []
            for value in getattr(photo, "sizes", ()):
                if hasattr(value, "size"):
                    sizes.append(value.size)
                if getattr(value, "sizes", None):
                    sizes.extend(value.sizes)
            size = max(sizes) if sizes else -1
        date = getattr(message, "date", None)
        data = dict(account=str(account), chat=str(chat), message_id=message.id, slot=slot,
                    file_id=f"{kind}:{obj.id}", name=filename, size=size,
                    date=date.isoformat() if date else "", chat_title=title, source=source or str(chat))
        data["item_key"] = file_key(account, chat, message.id, slot, data["file_id"])
        records.append(data)
    return records


async def cancellable_wait(seconds, cancel):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel.is_set():
            raise asyncio.CancelledError()
        await asyncio.sleep(min(0.25, end - time.monotonic()))


async def resolve_channel(client, source):
    clean, topic = parse_channel_input(source)
    if str(clean).lstrip("-").isdigit():
        # IDs selected from dialogs keep Telegram's signed peer identity.
        return await client.get_entity(int(clean)), topic
    return await fetch_channel(client, clean), topic


async def scan_history(client, store, account, sources, cancel, progress=None, on_batch=None,
                       start=None, end=None, limit=None, topic_id=None):
    """Telethon paginates iter_messages to exhaustion; limit=None means all history."""
    total_files, scanned, failures = 0, 0, []
    for source in sources:
        if cancel.is_set():
            break
        try:
            entity, link_topic = await resolve_channel(client, source)
            chat = str(get_peer_id(entity))
            title = getattr(entity, "title", None) or getattr(entity, "first_name", None) or chat
            offset, batch, per_chat = 0, [], 0
            done = False
            retries = 0
            while not done and not cancel.is_set():
                try:
                    params = dict(limit=None if limit is None else max(0, limit - per_chat), offset_id=offset)
                    if end:
                        params["offset_date"] = end
                    if topic_id or link_topic:
                        params["reply_to"] = topic_id or link_topic
                    async for message in client.iter_messages(entity, **params):
                        if cancel.is_set():
                            break
                        offset = message.id
                        scanned += 1
                        per_chat += 1
                        date = getattr(message, "date", None)
                        if date and date.tzinfo is None:
                            date = date.replace(tzinfo=timezone.utc)
                        if start and date and date < start:
                            done = True
                            break
                        records = media_records(message, account, chat, title, source)
                        if end and date and date >= end:
                            records = []
                        batch.extend(records)
                        total_files += len(records)
                        if len(batch) >= 200:
                            await asyncio.to_thread(store.upsert_media, batch)
                            if on_batch:
                                on_batch(len(batch))
                            batch = []
                        if progress and scanned % 100 == 0:
                            progress(f"{title}: 메시지 {per_chat:,}개 조회 / 전체 파일 {total_files:,}개 발견")
                        # Yield even when the test/cache iterator produces messages without I/O.
                        if scanned % 100 == 0:
                            await asyncio.sleep(0)
                    done = True
                except FloodWaitError as error:
                    if progress:
                        progress(f"Telegram 요청 제한: {error.seconds}초 대기")
                    await cancellable_wait(error.seconds, cancel)
                except (OSError, asyncio.TimeoutError):
                    retries += 1
                    if retries >= 3:
                        raise
                    await cancellable_wait(retries * 2, cancel)
            if batch:
                await asyncio.to_thread(store.upsert_media, batch)
                if on_batch:
                    on_batch(len(batch))
        except asyncio.CancelledError:
            break
        except Exception as error:
            failures.append(f"{source}: {type(error).__name__}")
    return {"scanned": scanned, "files": total_files, "cancelled": cancel.is_set(), "errors": failures}


class DownloadEngine:
    def __init__(self, client, store: SmartStore, account, cancel=None, progress=None, changed=None, max_speed_kb=0):
        self.client, self.store, self.account = client, store, str(account)
        self.cancel = cancel or threading.Event()
        self.progress, self.changed = progress, changed
        self.max_speed_kb = max_speed_kb
        self._file_locks = {}

    async def run(self, concurrency=3):
        items = self.store.items(self.account, ["queued"])
        queue = asyncio.Queue()
        for item in items:
            queue.put_nowait(item)

        async def consume():
            while not self.cancel.is_set():
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                lock = self._file_locks.setdefault(item["file_id"], asyncio.Lock())
                async with lock:
                    await self.download(item)
                queue.task_done()

        try:
            await asyncio.gather(*(consume() for _ in range(max(1, min(8, concurrency)))))
        finally:
            if self.cancel.is_set():
                for item in self.store.items(self.account, ["queued", "downloading", "verifying"]):
                    self.store.update(item["item_key"], phase="paused", error="사용자가 일시정지함")
            if self.changed:
                self.changed()

    async def download(self, item):
        key = item["item_key"]
        if self.cancel.is_set():
            self.store.update(key, phase="paused")
            return
        try:
            existing = await asyncio.to_thread(self.store.verified_telegram_duplicate, item, self.cancel)
            if existing:
                self.store.complete_duplicate(item, existing)
                return
            self.store.update(key, phase="downloading", error="")
            if self.changed:
                self.changed()
            ready = self.store.stage(item)
            if not ready.is_file():
                for attempt in range(3):
                    try:
                        if self.cancel.is_set():
                            raise asyncio.CancelledError()
                        entity = await self.client.get_input_entity(int(item["chat"]))
                        message = await self.client.get_messages(entity, ids=item["message_id"])
                        if not message:
                            raise ValueError("메시지가 삭제되었거나 접근할 수 없습니다.")
                        records = media_records(message, self.account, item["chat"])
                        if not any(r["file_id"] == item["file_id"] and r["slot"] == item["slot"] and r["size"] == item["size"] for r in records):
                            raise ValueError("Telegram 파일이 변경되었습니다. 목록을 다시 수집하세요.")
                        target = message.media
                        if isinstance(target, MessageMediaPaidMedia):
                            target = target.extended_media[item["slot"]].media
                        await self.transfer(item, target, ready)
                        break
                    except FloodWaitError as error:
                        if self.progress:
                            self.progress(key, 0, item["size"], f"요청 제한: {error.seconds}초 대기")
                        # Even the last attempt must respect the server's full waiting period.
                        GLOBAL_FLOODGATE.trip(error.seconds)
                        await cancellable_wait(error.seconds, self.cancel)
                        if attempt == 2:
                            raise
                    except (OSError, asyncio.TimeoutError, FileReferenceExpiredError):
                        if attempt == 2:
                            raise
                        await cancellable_wait((attempt + 1) * 2, self.cancel)
            if self.cancel.is_set():
                raise asyncio.CancelledError()
            self.store.update(key, phase="verifying")
            if self.changed:
                self.changed()
            await asyncio.to_thread(self.store.finalize, item, self.cancel)
        except (asyncio.CancelledError, InterruptedError):
            # Do not downgrade a durable publication intent after files have been saved.
            current = self.store.get(key)
            if current["phase"] == "committing":
                await asyncio.to_thread(self.store.recover_publication, current)
            else:
                self.store.update(key, phase="paused", error="일시정지됨 — 임시 파일 유지")
        except Exception as error:
            current = self.store.get(key)
            if current["phase"] == "committing" and await asyncio.to_thread(self.store.recover_publication, current):
                return
            detail = str(error) if isinstance(error, (ValueError, OSError)) else type(error).__name__
            self.store.update(key, phase="failed", error=detail)
            self.store.event(key, "failed", detail)
        finally:
            if self.changed:
                self.changed()

    async def transfer(self, item, target, ready: Path):
        started, last = time.monotonic(), [time.monotonic(), 0]
        first = [None]

        async def progress(current, total):
            if self.cancel.is_set():
                raise asyncio.CancelledError()
            if first[0] is None:
                first[0] = current
            elapsed = max(time.monotonic() - started, 0.001)
            if self.max_speed_kb:
                delay = (current - first[0]) / (self.max_speed_kb * 1024) - elapsed
                if delay > 0:
                    await cancellable_wait(delay, self.cancel)
            now = time.monotonic()
            if now - last[0] >= 0.25 or current == total:
                speed = max(0, current - last[1]) / max(now - last[0], 0.001)
                if self.progress:
                    self.progress(item["item_key"], current, total, f"{speed / 1024 / 1024:.2f} MB/s")
                last[:] = [now, current]

        if item["size"] > 1024 * 1024:
            ok = await fast_download_file(self.client, target, str(ready), item["size"],
                                          progress_callback=progress, cancel_event=self.cancel, workers=4)
            if self.cancel.is_set():
                raise asyncio.CancelledError()
            if ok:
                return
        # Separate sequential partials from preallocated parallel .part files.
        partial = ready.with_name("payload.stream.part")
        if partial.is_symlink():
            raise OSError("임시 파일에 링크를 사용할 수 없습니다.")
        offset = partial.stat().st_size if partial.exists() else 0
        offset = offset // CHUNK_SIZE * CHUNK_SIZE
        if item["size"] >= 0 and offset > item["size"]:
            offset = 0
        first[0] = offset
        with partial.open("r+b" if partial.exists() else "w+b") as stream:
            stream.truncate(offset)
            stream.seek(offset)
            iterator = self.client.iter_download(target, offset=offset, request_size=CHUNK_SIZE)
            try:
                while True:
                    if not await GLOBAL_FLOODGATE.acquire(self.cancel):
                        raise asyncio.CancelledError()
                    try:
                        chunk = await iterator.__anext__()
                    except StopAsyncIteration:
                        break
                    if self.cancel.is_set():
                        raise asyncio.CancelledError()
                    stream.write(chunk)
                    offset += len(chunk)
                    await progress(offset, item["size"])
            finally:
                close = getattr(iterator, "close", None) or getattr(iterator, "aclose", None)
                if close:
                    await close()
            stream.flush()
            os.fsync(stream.fileno())
        if item["size"] >= 0 and offset != item["size"]:
            raise OSError("다운로드가 중간에 종료되었습니다. 다시 시도할 수 있습니다.")
        os.replace(partial, ready)  # Application-owned staging path only.
