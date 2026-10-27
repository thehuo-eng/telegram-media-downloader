"""Additive SQLite schema. Legacy media_cache/tasks tables remain untouched."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from smart.rules import Category, Classification, absolute_folder, safe_filename

TERMINAL = {"completed", "duplicate"}
ACTIVE = {"queued", "downloading", "verifying", "committing"}
STAGE_DIR = ".tsd-staging"


def now():
    return datetime.now(timezone.utc).isoformat()


def file_key(account, chat, message_id, slot=0, file_id=""):
    values = [str(account), str(chat), int(message_id), int(slot), str(file_id)]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def hash_file(path, cancel=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise OSError("일반 파일만 검사할 수 있습니다.")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancel and cancel.is_set():
                raise InterruptedError("검사가 취소되었습니다.")
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError("검사 도중 파일이 변경되었습니다. 다시 시도하세요.")
    return digest.hexdigest()


class SmartStore:
    _locks: dict[str, threading.RLock] = {}
    _guard = threading.Lock()

    def __init__(self, db_path):
        self.path = str(Path(db_path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._guard:
            self.publish_lock = self._locks.setdefault(self.path, threading.RLock())
        self.migrate()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self):
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS smart_schema(version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS smart_categories(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS smart_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS smart_media(
                    item_key TEXT PRIMARY KEY, account TEXT NOT NULL, chat TEXT NOT NULL,
                    message_id INTEGER NOT NULL, slot INTEGER NOT NULL DEFAULT 0,
                    file_id TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL,
                    date TEXT NOT NULL DEFAULT '', chat_title TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '', manual_id TEXT, selected INTEGER NOT NULL DEFAULT 1,
                    phase TEXT NOT NULL DEFAULT 'discovered', category_id TEXT, category TEXT,
                    folder TEXT, rule TEXT, conflicts TEXT NOT NULL DEFAULT '[]',
                    final_path TEXT, sha256 TEXT, stage_token TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL,
                    UNIQUE(account,chat,message_id,slot,file_id)
                );
                CREATE INDEX IF NOT EXISTS smart_telegram_file ON smart_media(account,file_id,size,phase);
                CREATE INDEX IF NOT EXISTS smart_queue ON smart_media(account,phase,updated);
                CREATE TABLE IF NOT EXISTS smart_known_files(
                    path_key TEXT PRIMARY KEY, path TEXT NOT NULL, size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL, sha256 TEXT, updated TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS smart_file_size ON smart_known_files(size);
                CREATE INDEX IF NOT EXISTS smart_file_hash ON smart_known_files(sha256,size);
                CREATE TABLE IF NOT EXISTS smart_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, item_key TEXT NOT NULL,
                    event TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL
                );
                INSERT OR IGNORE INTO smart_schema VALUES(1);
            """)

    def setting(self, key, default=None):
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM smart_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connection() as conn:
            conn.execute("INSERT INTO smart_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, json.dumps(value, ensure_ascii=False)))

    def categories(self):
        with self.connection() as conn:
            values = conn.execute("SELECT payload FROM smart_categories").fetchall()
        return sorted([Category(**json.loads(r[0])) for r in values], key=lambda c: (c.priority, c.id))

    def save_categories(self, categories):
        ids, names = set(), set()
        for i, cat in enumerate(categories):
            cat.validate()
            cat.priority = i
            if cat.id in ids or cat.name.casefold() in names:
                raise ValueError("범주 이름은 서로 다르게 지정하세요.")
            ids.add(cat.id)
            names.add(cat.name.casefold())
        defaults = [c for c in categories if c.enabled and c.is_default]
        if len(defaults) > 1:
            raise ValueError("기본 범주는 하나만 지정할 수 있습니다.")
        if any(c.extensions or c.keywords for c in defaults):
            raise ValueError("기본 범주는 키워드·확장자를 비워 두세요. 형식별 범주는 확장자만 지정합니다.")
        with self.connection() as conn:
            # Configuration rows only; file histories and manual IDs are retained.
            conn.execute("DELETE FROM smart_categories")
            conn.executemany("INSERT INTO smart_categories VALUES(?,?)",
                             [(c.id, json.dumps(c.to_dict(), ensure_ascii=False)) for c in categories])

    def upsert_media(self, records):
        with self.connection() as conn:
            for data in records:
                data = dict(data)
                key = file_key(data["account"], data["chat"], data["message_id"], data.get("slot", 0), data["file_id"])
                conn.execute("""INSERT INTO smart_media
                    (item_key,account,chat,message_id,slot,file_id,name,size,date,chat_title,source,stage_token,updated)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(item_key) DO UPDATE SET
                    name=excluded.name,size=excluded.size,date=excluded.date,
                    chat_title=excluded.chat_title,source=excluded.source""",
                    (key, str(data["account"]), str(data["chat"]), data["message_id"], data.get("slot", 0),
                     data["file_id"], data["name"], data["size"], data.get("date", ""),
                     data.get("chat_title", ""), data.get("source", data["chat"]), uuid.uuid4().hex, now()))

    def items(self, account=None, phases=None):
        query, args = "SELECT * FROM smart_media WHERE 1=1", []
        if account is not None:
            query += " AND account=?"
            args.append(str(account))
        if phases:
            query += " AND phase IN (" + ",".join("?" for _ in phases) + ")"
            args.extend(phases)
        with self.connection() as conn:
            return [dict(r) for r in conn.execute(query + " ORDER BY date DESC,message_id DESC", args)]

    def get(self, key):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM smart_media WHERE item_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def update(self, key, **values):
        allowed = {"manual_id", "selected", "phase", "category_id", "category", "folder", "rule", "conflicts", "final_path", "sha256", "error"}
        if not values or not set(values) <= allowed:
            raise ValueError("허용되지 않은 이력 필드입니다.")
        values["updated"] = now()
        with self.connection() as conn:
            conn.execute("UPDATE smart_media SET " + ",".join(f"{k}=?" for k in values) + " WHERE item_key=?",
                         (*values.values(), key))

    def select_many(self, keys, selected):
        with self.connection() as conn:
            conn.executemany("UPDATE smart_media SET selected=? WHERE item_key=?", [(int(selected), k) for k in keys])

    def enqueue(self, plans):
        with self.connection() as conn:
            for key, plan in plans:
                if not plan.allowed:
                    continue
                conn.execute("""UPDATE smart_media SET phase='queued', category_id=?,category=?,folder=?,rule=?,
                    conflicts=?,error='',updated=? WHERE item_key=? AND phase NOT IN ('downloading','verifying','committing')""",
                    (plan.category_id, plan.category, absolute_folder(plan.folder), plan.rule,
                     json.dumps(plan.conflicts, ensure_ascii=False), now(), key))

    def recover(self):
        # An interrupted queue is always resumed explicitly by the user.
        with self.connection() as conn:
            conn.execute("UPDATE smart_media SET phase='paused',error='종료 후 복구됨 — 재개 가능' WHERE phase IN ('queued','downloading','verifying')")
        # Preserve committing intents until the verified publication is recovered.
        for item in self.items(phases=["committing"]):
            self.recover_publication(item)

    def event(self, key, event, detail):
        with self.connection() as conn:
            conn.execute("INSERT INTO smart_events(item_key,event,detail,created) VALUES(?,?,?,?)", (key, event, detail, now()))

    def stage(self, item, create=True):
        root = Path(absolute_folder(item["folder"]))
        stage = root / STAGE_DIR / item["stage_token"]
        if not re_token(item["stage_token"]):
            raise ValueError("잘못된 임시 파일 식별자입니다.")
        # Refuse redirected staging directories, including Windows junctions.
        for part in (root / STAGE_DIR, stage):
            if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
                raise OSError("임시 폴더에 링크 또는 정션을 사용할 수 없습니다.")
        if create:
            stage.mkdir(parents=True, exist_ok=True)
        if not stage.resolve().is_relative_to(root.resolve()):
            raise OSError("임시 폴더가 지정한 저장 폴더를 벗어났습니다.")
        return stage / "payload.ready"

    def _catalog(self, conn, path, digest=None):
        path = Path(path).resolve()
        stat = path.stat()
        conn.execute("""INSERT INTO smart_known_files VALUES(?,?,?,?,?,?) ON CONFLICT(path_key) DO UPDATE SET
            path=excluded.path,size=excluded.size,mtime_ns=excluded.mtime_ns,
            sha256=CASE WHEN smart_known_files.size=excluded.size AND smart_known_files.mtime_ns=excluded.mtime_ns
                THEN COALESCE(excluded.sha256,smart_known_files.sha256) ELSE excluded.sha256 END,updated=excluded.updated""",
            (path_key(path), str(path), stat.st_size, stat.st_mtime_ns, digest, now()))

    def index_folders(self, folders, cancel=None, progress=None):
        count, errors, seen = 0, [], set()
        for folder in folders:
            root = Path(absolute_folder(folder))
            if not root.is_dir():
                errors.append(f"폴더 없음: {root}")
                continue
            def walk_error(error):
                errors.append(f"폴더 접근 실패: {error.filename}")
            for current, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
                dirs[:] = [d for d in dirs if d != STAGE_DIR and not Path(current, d).is_symlink()
                           and not (hasattr(Path(current, d), 'is_junction') and Path(current, d).is_junction())]
                with self.connection() as conn:
                    for name in files:
                        if cancel and cancel.is_set():
                            return {"count": count, "errors": errors, "cancelled": True}
                        path = Path(current, name)
                        if path.is_symlink() or name.endswith((".part", ".part.meta", ".ready")):
                            continue
                        key = path_key(path)
                        if key in seen:
                            continue
                        seen.add(key)
                        try:
                            self._catalog(conn, path)
                            count += 1
                        except OSError:
                            errors.append(f"파일 접근 실패: {path}")
                        if progress and count % 100 == 0:
                            progress(count)
                        if count % 200 == 0:
                            conn.commit()
                            time.sleep(0.005)  # Let short GUI configuration writes through.
        return {"count": count, "errors": errors, "cancelled": False}

    def telegram_candidates(self, item):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("""SELECT DISTINCT m.final_path,m.sha256,k.size,k.mtime_ns
                FROM smart_media m LEFT JOIN smart_known_files k ON k.path=m.final_path
                WHERE m.account=? AND m.file_id=? AND m.size=?
                AND m.final_path IS NOT NULL AND m.sha256 IS NOT NULL""",
                (item["account"], item["file_id"], item["size"]))]

    def verified_telegram_duplicate(self, item, cancel=None):
        for candidate in self.telegram_candidates(item):
            path = Path(candidate["final_path"])
            try:
                if path.is_file() and not path.is_symlink() and path.stat().st_size == item["size"]:
                    if hash_file(path, cancel) == candidate["sha256"]:
                        return candidate
            except OSError:
                continue
        return None

    def complete_duplicate(self, item, existing, reason="동일 Telegram 파일 — 기존 파일 해시 확인"):
        self.update(item["item_key"], phase="duplicate", selected=0, final_path=existing["final_path"], sha256=existing["sha256"], error=reason)
        self.event(item["item_key"], "duplicate", reason + ": " + existing["final_path"])
        self.cleanup_staging(item)

    def cleanup_staging(self, item):
        """Only exact, application-owned transient names after a successful DB commit."""
        parent = self.stage(item, create=False).parent
        for name in ("payload.ready", "payload.ready.part", "payload.ready.part.meta",
                     "payload.ready.part.meta.tmp", "payload.stream.part", "payload.local.part"):
            path = parent / name
            try:
                path.unlink(missing_ok=True)
            except OSError:
                self.event(item["item_key"], "temporary_cleanup_pending", str(path))

    def recover_publication(self, item):
        path = Path(item.get("final_path") or "")
        try:
            if item.get("sha256") and path.is_file() and hash_file(path) == item["sha256"]:
                with self.connection() as conn:
                    self._catalog(conn, path, item["sha256"])
                    conn.execute("UPDATE smart_media SET phase='completed',selected=0,error='' WHERE item_key=?", (item["item_key"],))
                return True
        except OSError:
            pass
        self.update(item["item_key"], phase="paused", error="저장 중 종료됨 — 임시 파일에서 재개 가능")
        return False

    def find_content_duplicate(self, size, digest, cancel=None, excluded_roots=()):
        roots = [Path(p).resolve() for p in excluded_roots]
        with self.connection() as conn:
            candidates = conn.execute("SELECT * FROM smart_known_files WHERE size=? ORDER BY sha256=? DESC", (size, digest)).fetchall()
            for row in candidates:
                path = Path(row["path"])
                if any(path.resolve().is_relative_to(root) for root in roots):
                    continue
                try:
                    stat = path.stat()
                    if path.is_symlink() or not path.is_file() or stat.st_size != size:
                        continue
                    if row["sha256"] and row["sha256"] != digest and stat.st_mtime_ns == row["mtime_ns"]:
                        continue
                    actual = hash_file(path, cancel)
                    self._catalog(conn, path, actual)
                    conn.commit()
                    if actual == digest:
                        return {"final_path": str(path), "sha256": digest}
                except FileNotFoundError:
                    continue
        return None

    def finalize(self, item, cancel=None, source_path=None, excluded_roots=()):
        # source_path is only supplied after an explicit local-file move selection.
        ready = Path(source_path) if source_path is not None else self.stage(item)
        if ready.is_symlink() or not ready.is_file():
            raise OSError("검증할 임시 파일이 없습니다.")
        size = ready.stat().st_size
        source_stat = ready.stat()
        if item["size"] >= 0 and size != item["size"]:
            raise OSError("검사할 파일의 크기가 수집한 원본 크기와 다릅니다.")
        digest = hash_file(ready, cancel)
        with self.publish_lock:
            existing = self.find_content_duplicate(size, digest, cancel, excluded_roots)
            if existing:
                self.complete_duplicate(item, existing, "SHA-256 내용 중복")
                return existing["final_path"], True
            root = Path(absolute_folder(item["folder"]))
            root.mkdir(parents=True, exist_ok=True)
            name = safe_filename(item["name"])
            stem, suffix = os.path.splitext(name)
            counter = 1
            while True:
                target = root / (name if counter == 1 else f"{stem} ({counter}){suffix}")
                if target.exists():
                    # Even without an initial index, check a file occupying this exact name.
                    if target.is_file() and not target.is_symlink() and target.stat().st_size == size:
                        actual = hash_file(target, cancel)
                        with self.connection() as conn:
                            self._catalog(conn, target, actual)
                        if actual == digest:
                            self.complete_duplicate(item, {"final_path": str(target), "sha256": digest}, "SHA-256 내용 중복 — 기존 이름")
                            return str(target), True
                    counter += 1
                    continue
                if len(str(target).encode("utf-16-le")) > 480:
                    raise OSError("저장 경로가 너무 깁니다. 더 짧은 폴더를 지정하세요.")
                # Durable intent allows recovery after publication but before DB commit.
                if source_path is not None:
                    current_stat = ready.stat()
                    if (current_stat.st_size, current_stat.st_mtime_ns, current_stat.st_ino, current_stat.st_dev) != (
                            source_stat.st_size, source_stat.st_mtime_ns, source_stat.st_ino, source_stat.st_dev):
                        raise OSError("검사 후 원본이 변경되어 이동하지 않았습니다. 폴더를 다시 읽으세요.")
                if cancel and cancel.is_set():
                    raise InterruptedError("저장 전에 일시정지됨")
                self.update(item["item_key"], phase="committing", final_path=str(target), sha256=digest)
                try:
                    if os.name == "nt":
                        os.rename(ready, target)  # Windows rename fails if target already exists.
                    else:
                        os.link(ready, target)  # Atomic, never replaces an existing file.
                    break
                except FileExistsError:
                    counter += 1
            with self.connection() as conn:
                self._catalog(conn, target, digest)
                conn.execute("UPDATE smart_media SET phase='completed',selected=0,error='',updated=? WHERE item_key=?", (now(), item["item_key"]))
                conn.execute("INSERT INTO smart_events(item_key,event,detail,created) VALUES(?,?,?,?)",
                             (item["item_key"], "completed", str(target), now()))
            self.cleanup_staging(item)
            return str(target), False


def re_token(value):
    return len(value) == 32 and all(ch in "0123456789abcdef" for ch in value)
