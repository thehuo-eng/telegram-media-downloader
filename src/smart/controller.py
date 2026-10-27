from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Signal
from telethon.errors import FloodWaitError

from smart.pipeline import DownloadEngine, scan_history, cancellable_wait
from smart.rules import Classifier, FileFilter
from smart.store import ACTIVE, TERMINAL


class SmartController(QObject):
    filter_key = "filter"
    account_changed = Signal(str)
    dialogs_ready = Signal(object)
    snapshot_ready = Signal(object)
    status = Signal(str)
    error = Signal(str)
    changed = Signal()
    activity = Signal(str, bool)
    file_progress = Signal(str, object, object, str)
    index_done = Signal(object)

    def __init__(self, worker, store, parent=None):
        super().__init__(parent)
        self.worker, self.store = worker, store
        self.account = None
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="smart-files")
        self.recovery = self.executor.submit(self.store.recover)
        self.scan_cancel, self.download_cancel, self.index_cancel = (threading.Event() for _ in range(3))
        self.scanning = self.downloading = self.indexing = self.refreshing = False
        self.refresh_again = False
        self.generation = 0
        self.batch_keys = set()
        self.futures = set()
        self.closed = False
        self.worker.signals.auth_success.connect(self.connect_account)
        self.worker.signals.auth_needed.connect(self.disconnected)

    def classifier(self):
        fallback = self.store.setting("fallback", str(Path.home() / "Downloads" / "Telegram" / "미분류"))
        data = self.store.setting(self.filter_key, None)
        return Classifier(self.store.categories(), fallback, FileFilter(**data) if data else None)

    def _submit(self, coroutine):
        if not self.worker.loop or not self.worker.loop.is_running():
            coroutine.close()
            self.error.emit("텔레그램 연결을 먼저 완료하세요.")
            return None
        future = asyncio.run_coroutine_threadsafe(coroutine, self.worker.loop)
        self.futures.add(future)
        def finished(result):
            self.futures.discard(result)
            if self.closed or result.cancelled():
                return
            error = result.exception()
            if error:
                self.error.emit(f"작업 실패: {type(error).__name__}")
        future.add_done_callback(finished)
        return future

    def disconnected(self):
        self.generation += 1
        self.account = None
        self.scan_cancel.set()
        self.download_cancel.set()
        self.account_changed.emit("")

    def connect_account(self):
        async def bind():
            me = await self.worker.client.get_me()
            self.account = str(me.id)
            self.generation += 1
            self.store.set_setting("last_account", self.account)
            self.account_changed.emit(self.account)
            self.changed.emit()
        self._submit(bind())

    def list_dialogs(self):
        if not self.account:
            self.error.emit("먼저 텔레그램에 로그인하세요.")
            return
        async def load():
            self.activity.emit("dialogs", True)
            results, seen = [], set()
            try:
                for attempt in range(3):
                    try:
                        async for dialog in self.worker.client.iter_dialogs(limit=None):
                            if dialog.id not in seen:
                                seen.add(dialog.id)
                                results.append({"id": str(dialog.id), "title": dialog.name or str(dialog.id)})
                        break
                    except FloodWaitError as error:
                        self.status.emit(f"채팅 목록 요청 제한: {error.seconds}초 대기")
                        await cancellable_wait(error.seconds, self.scan_cancel)
                        if attempt == 2:
                            raise
                self.dialogs_ready.emit(results)
                self.status.emit(f"채팅방 {len(results):,}개를 불러왔습니다.")
            finally:
                self.activity.emit("dialogs", False)
        self.scan_cancel.clear()
        self._submit(load())

    def scan(self, sources, **options):
        if not self.account or self.scanning:
            self.error.emit("로그인 상태와 진행 중인 조회를 확인하세요.")
            return
        self.scan_cancel.clear()
        self.scanning = True
        account = self.account
        async def run():
            self.activity.emit("scan", True)
            try:
                result = await scan_history(self.worker.client, self.store, account, sources, self.scan_cancel,
                                            self.status.emit, lambda count: self.changed.emit(), **options)
                self.status.emit(f"조회 {'취소' if result['cancelled'] else '완료'}: 메시지 {result['scanned']:,}개 / 파일 {result['files']:,}개")
                if result["errors"]:
                    self.error.emit("일부 채팅방 조회 실패:\n" + "\n".join(result["errors"]))
            finally:
                self.scanning = False
                self.changed.emit()
                self.activity.emit("scan", False)
        if not self._submit(run()):
            self.scanning = False

    def refresh(self):
        if self.closed:
            return
        if self.refreshing:
            self.refresh_again = True
            return
        self.refreshing = True
        generation = self.generation
        account = self.account or self.store.setting("last_account")
        def build():
            self.recovery.result()
            classifier = self.classifier()
            items = self.store.items(account) if account else []
            known = {(i["account"], i["file_id"], i["size"]) for i in items if i["final_path"] and i["sha256"]}
            preview, queue = [], []
            for item in items:
                plan = classifier.classify(item["name"], item["manual_id"])
                item["plan"] = plan
                item["duplicate_hint"] = "이력 일치 — 파일 재검사 예정" if (item["account"], item["file_id"], item["size"]) in known else "내용 미확인 — 다운로드 후 검사"
                preview.append(item)
                if item["phase"] != "discovered":
                    queue.append(item)
            return {"preview": preview, "queue": queue, "categories": classifier.categories, "generation": generation}
        future = self.executor.submit(build)
        def done(result):
            self.refreshing = False
            if self.closed:
                return
            try:
                self.snapshot_ready.emit(result.result())
            except Exception as error:
                self.error.emit(f"목록 불러오기 실패: {error}")
            if self.refresh_again:
                self.refresh_again = False
                self.changed.emit()
        future.add_done_callback(done)

    def start_downloads(self, plans=None, retry=False):
        if not self.account or self.downloading:
            self.error.emit("로그인 상태를 확인하세요. 진행 중인 다운로드는 먼저 일시정지하세요.")
            return
        if self.indexing:
            self.error.emit("기존 파일 인덱싱이 완료된 뒤 다운로드를 시작하세요.")
            return
        self.download_cancel.clear()
        self.downloading = True
        account = self.account
        async def run():
            self.activity.emit("download", True)
            try:
                await asyncio.wrap_future(self.recovery)
                if plans is not None:
                    await asyncio.to_thread(self.store.enqueue, plans)
                else:
                    phases = ["failed"] if retry else ["paused", "queued"]
                    for item in self.store.items(account, phases):
                        self.store.update(item["item_key"], phase="queued", error="")
                engine = DownloadEngine(self.worker.client, self.store, account, self.download_cancel,
                                        self.file_progress.emit, self.changed.emit,
                                        self.store.setting("max_speed_kb", 0))
                self.batch_keys = {i["item_key"] for i in self.store.items(account, ["queued"])}
                await engine.run(self.store.setting("concurrency", 3))
                self.status.emit("다운로드 일시정지됨" if self.download_cancel.is_set() else "대기열 처리 완료 — 완료·중복·실패 상태를 확인하세요.")
            finally:
                self.downloading = False
                self.activity.emit("download", False)
                self.changed.emit()
        if not self._submit(run()):
            self.downloading = False

    def index(self):
        if self.indexing or self.downloading:
            self.error.emit("다운로드 또는 인덱싱이 진행 중입니다.")
            return
        folders = [c.folder for c in self.store.categories()]
        folders.append(self.classifier().fallback)
        folders.extend(self.store.setting("extra_folders", []))
        self.index_cancel.clear()
        self.indexing = True
        self.activity.emit("index", True)
        future = self.executor.submit(self.store.index_folders, list(dict.fromkeys(folders)), self.index_cancel,
                                      lambda count: self.status.emit(f"기존 파일 {count:,}개 인덱싱 중…"))
        def done(result):
            self.indexing = False
            if self.closed:
                return
            self.activity.emit("index", False)
            try:
                self.index_done.emit(result.result())
            except Exception as error:
                self.error.emit(f"인덱싱 실패: {error}")
            self.changed.emit()
        future.add_done_callback(done)

    def shutdown(self):
        self.closed = True
        self.scan_cancel.set()
        self.download_cancel.set()
        self.index_cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
