"""Offline classification of completed local downloads. No Telegram client calls."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import time
import uuid

from smart.rules import absolute_folder
from smart.store import SmartStore, STAGE_DIR, file_key, hash_file, path_key

LOCAL_ACCOUNT = "local-files"
CHUNK = 1024 * 1024
PARTIAL_SUFFIXES = (".part", ".tmp", ".crdownload", ".download", ".partial", ".ready")


def signature(info):
    return [info.st_size, info.st_mtime_ns, str(info.st_dev), str(info.st_ino)]


def cancelled(cancel):
    if cancel and cancel.is_set():
        raise InterruptedError("일시정지됨 — 원본과 임시 파일 유지")


def same_volume(source, destination):
    return source.stat().st_dev == destination.stat().st_dev


class LocalStore(SmartStore):
    def migrate(self):
        super().migrate()
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS smart_local_files(
                    item_key TEXT PRIMARY KEY, source_path TEXT NOT NULL,
                    source_root TEXT NOT NULL, signature TEXT NOT NULL,
                    last_scan TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'copy'
                );
                CREATE INDEX IF NOT EXISTS smart_local_scan ON smart_local_files(last_scan);
            """)

    def add_local(self, entries, scan_id):
        self.upsert_media(entries)
        with self.connection() as conn:
            conn.executemany("""INSERT INTO smart_local_files
                (item_key,source_path,source_root,signature,last_scan) VALUES(?,?,?,?,?)
                ON CONFLICT(item_key) DO UPDATE SET last_scan=excluded.last_scan""",
                [(r["item_key"], r["source"], r["source_root"], json.dumps(r["signature"]), scan_id) for r in entries])

    def local_items(self, phases=None, scan_id=None):
        query = "SELECT m.*,l.source_path,l.source_root,l.signature,l.mode,l.last_scan FROM smart_media m JOIN smart_local_files l USING(item_key) WHERE m.account=?"
        args = [LOCAL_ACCOUNT]
        if phases:
            query += " AND m.phase IN (" + ",".join("?" for _ in phases) + ")"
            args.extend(phases)
        if scan_id:
            query += " AND l.last_scan=?"
            args.append(scan_id)
        with self.connection() as conn:
            return [dict(r) for r in conn.execute(query + " ORDER BY m.name,m.item_key", args)]

    def enqueue_local(self, plans, mode="copy"):
        if mode not in ("copy", "move"):
            raise ValueError("복사 또는 이동을 선택하세요.")
        self.enqueue(plans)
        with self.connection() as conn:
            conn.executemany("UPDATE smart_local_files SET mode=? WHERE item_key=? AND item_key IN (SELECT item_key FROM smart_media WHERE phase='queued')",
                             [(mode, key) for key, plan in plans if plan.allowed])


def scan_local(store, folders, cancel=None, progress=None, recursive=True):
    roots = list(dict.fromkeys(absolute_folder(p) for p in folders))
    if not roots or any(not Path(p).is_dir() for p in roots):
        raise ValueError("내보내기가 끝난 원본 폴더를 선택하세요.")
    scan_id = uuid.uuid4().hex
    store.set_setting("local_active_scan", scan_id)
    store.set_setting("local_sources", roots)
    count = total = skipped = 0
    errors, seen, batch = [], set(), []
    database_key = path_key(store.path)
    try:
        for root in roots:
            for current, dirs, files in os.walk(root, followlinks=False, onerror=lambda e: errors.append(str(e))):
                cancelled(cancel)
                dirs[:] = [d for d in dirs if recursive and d not in (STAGE_DIR, ".git", ".venv")
                           and not Path(current, d).is_symlink()
                           and not (hasattr(Path(current, d), "is_junction") and Path(current, d).is_junction())]
                for name in files:
                    cancelled(cancel)
                    path = Path(current, name)
                    if name.lower().endswith(PARTIAL_SUFFIXES) or path.is_symlink() or path_key(path) in (database_key, database_key + '-wal', database_key + '-shm'):
                        skipped += 1
                        continue
                    try:
                        info = path.stat()
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        canonical = str(path.resolve())
                        if canonical in seen:
                            continue
                        seen.add(canonical)
                        sig = signature(info)
                        identity = hashlib.sha256(json.dumps([path_key(path), sig]).encode()).hexdigest()
                        chat = str(path.parent.resolve())
                        key = file_key(LOCAL_ACCOUNT, chat, 0, 0, identity)
                        batch.append(dict(item_key=key, account=LOCAL_ACCOUNT, chat=chat, message_id=0,
                            slot=0, file_id=identity, name=name, size=info.st_size,
                            date=datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                            chat_title=chat, source=canonical, source_root=root, signature=sig))
                        count += 1
                        total += info.st_size
                        if len(batch) >= 200:
                            store.add_local(batch, scan_id)
                            batch.clear()
                            if progress:
                                progress(count, total)
                    except OSError as error:
                        errors.append(f"{path}: {error}")
    except InterruptedError:
        pass
    if batch:
        store.add_local(batch, scan_id)
    return {"count": count, "bytes": total, "skipped": skipped, "errors": errors,
            "cancelled": bool(cancel and cancel.is_set()), "scan_id": scan_id}


def validate_locations(items, destinations):
    roots = {Path(i["source_root"]).resolve() for i in items}
    for folder in destinations:
        target = Path(absolute_folder(folder))
        if any(target.is_relative_to(root) or root.is_relative_to(target) for root in roots):
            raise ValueError(f"원본 폴더와 저장·중복 검사 폴더는 서로 겹치지 않게 선택하세요: {target}")


class LocalFileEngine:
    def __init__(self, store, cancel=None, progress=None, changed=None):
        self.store = store
        self.cancel = cancel or threading.Event()
        self.progress, self.changed = progress, changed

    def emit(self, item, current, message):
        if self.progress:
            self.progress(item["item_key"], current, item["size"], message)

    def verify_source(self, item):
        path = Path(item["source_path"])
        # An input changed since preview must be scanned again, never silently moved.
        if path.is_symlink() or not path.is_file() or signature(path.stat()) != json.loads(item["signature"]):
            raise OSError("원본 파일이 변경되었거나 없습니다. 내보내기 완료 후 폴더를 다시 읽으세요.")
        if path.resolve() != path:
            raise OSError("원본 경로가 링크 또는 정션으로 변경되었습니다.")
        return path

    def run(self):
        for item in self.store.local_items(["queued"]):
            if self.cancel.is_set():
                break
            self.process(item)
        if self.cancel.is_set():
            for item in self.store.local_items(["queued", "downloading", "verifying"]):
                self.store.update(item["item_key"], phase="paused", error="일시정지됨 — 원본과 임시 파일 유지")
        if self.changed:
            self.changed()

    def process(self, item):
        key = item["item_key"]
        try:
            cancelled(self.cancel)
            source = self.verify_source(item)
            validate_locations([item], [item["folder"]])
            destination = Path(item["folder"])
            destination.mkdir(parents=True, exist_ok=True)
            self.store.update(key, phase="verifying", error="")
            self.emit(item, 0, "SHA-256 중복 검사")
            if self.changed:
                self.changed()
            roots = self.store.setting("local_sources", [item["source_root"]])
            roots = list(dict.fromkeys([*roots, item["source_root"]]))
            # Same-volume moves use one verified rename, without a second full-size copy.
            if item["mode"] == "move" and same_volume(source, destination):
                final, duplicate = self.store.finalize(item, self.cancel, source_path=source, excluded_roots=roots)
            else:
                # Avoid allocating another large copy when a same-size candidate already exists.
                with self.store.connection() as conn:
                    has_candidates = conn.execute("SELECT 1 FROM smart_known_files WHERE size=? LIMIT 1", (item["size"],)).fetchone()
                if has_candidates:
                    digest = hash_file(source, self.cancel)
                    self.verify_source(item)
                    with self.store.publish_lock:
                        existing = self.store.find_content_duplicate(item["size"], digest, self.cancel, roots)
                        if existing:
                            self.store.complete_duplicate(item, existing, "SHA-256 내용 중복 — 원본 유지")
                            return
                ready = self.store.stage(item)
                if not ready.exists():
                    self.store.update(key, phase="downloading")
                    self.copy_resumable(item, source, ready)
                self.verify_source(item)
                self.store.update(key, phase="verifying")
                self.emit(item, item["size"], "저장 내용 검증")
                final, duplicate = self.store.finalize(item, self.cancel, excluded_roots=roots)
            if duplicate:
                self.store.update(key, error="SHA-256 내용 중복 — 원본 유지")
            elif item["mode"] == "move" and source.exists():
                # Cross-volume copies and POSIX hard-link publication remove the input only
                # after the final file is durable and both byte streams have been verified.
                try:
                    self.verify_source(item)
                    digest = self.store.get(key)["sha256"]
                    if hash_file(source, self.cancel) != digest or hash_file(final, self.cancel) != digest:
                        raise OSError("원본 또는 저장 파일이 달라 원본 제거를 보류했습니다.")
                    self.verify_source(item)
                    source.unlink()
                except OSError as error:
                    self.store.update(key, error=f"저장은 완료, 원본 유지: {error}")
                    self.store.event(key, "source_retained", str(source))
            self.emit(item, item["size"], "처리 완료")
        except InterruptedError:
            current = self.store.get(key)
            if current["phase"] == "committing":
                self.store.recover_publication(current)
            elif current["phase"] not in ("completed", "duplicate"):
                self.store.update(key, phase="paused", error="일시정지됨 — 원본과 임시 파일 유지")
        except Exception as error:
            current = self.store.get(key)
            if current["phase"] == "committing" and self.store.recover_publication(current):
                return
            self.store.update(key, phase="failed", error=str(error))
            self.store.event(key, "failed", str(error))
        finally:
            if self.changed:
                self.changed()

    def copy_resumable(self, item, source, ready):
        partial = ready.with_name("payload.local.part")
        if partial.is_symlink():
            raise OSError("임시 파일에 링크를 사용할 수 없습니다.")
        offset = min(partial.stat().st_size, item["size"]) if partial.exists() else 0
        if shutil.disk_usage(ready.parent).free < item["size"] - offset + CHUNK:
            raise OSError("저장 폴더의 여유 공간이 부족합니다. 공간을 확보하거나 이동 방식을 선택하세요.")
        started = last = time.monotonic()
        with source.open("rb") as src, partial.open("r+b" if partial.exists() else "w+b") as out:
            verified = 0
            while verified < offset:
                cancelled(self.cancel)
                count = min(CHUNK, offset - verified)
                if src.read(count) != out.read(count):
                    break
                verified += count
                tick = time.monotonic()
                if tick - last >= .2 or verified == offset:
                    self.emit(item, verified, "중간 파일 검증")
                    last = tick
            offset = verified
            src.seek(offset)
            out.seek(offset)
            out.truncate(offset)
            initial = offset
            while chunk := src.read(CHUNK):
                cancelled(self.cancel)
                out.write(chunk)
                offset += len(chunk)
                tick = time.monotonic()
                if tick - last >= .2 or offset >= item["size"]:
                    self.emit(item, offset, f"{(offset - initial) / max(tick - started, .001) / CHUNK:.1f} MB/s")
                    last = tick
            out.flush()
            os.fsync(out.fileno())
            if signature(os.fstat(src.fileno())) != json.loads(item["signature"]):
                raise OSError("복사 중 원본이 바뀌었습니다. 내보내기 완료 후 다시 읽으세요.")
        self.verify_source(item)
        if offset != item["size"]:
            raise OSError("복사 크기가 원본과 다릅니다.")
        os.rename(partial, ready)
