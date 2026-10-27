"""Qt coordinator for local-only file operations using the shared rules and tables."""
from pathlib import Path

from smart.controller import SmartController
from smart.local import LOCAL_ACCOUNT, LocalFileEngine, scan_local, validate_locations
from ui.components.smart_table import file_size


class LocalController(SmartController):
    filter_key = "local_filter"

    def __init__(self, worker, store, parent=None):
        super().__init__(worker, store, parent)
        self.account = LOCAL_ACCOUNT
        if store.setting(self.filter_key) is None:
            store.set_setting(self.filter_key, {"groups": [], "extra_extensions": ["pdf"]})

    def connect_account(self):
        pass

    def disconnected(self):
        pass

    def scan(self, sources, recursive=True):
        if self.scanning or self.downloading or self.indexing:
            self.error.emit("현재 작업을 완료하거나 일시정지한 뒤 폴더를 읽으세요.")
            return
        self.scan_cancel.clear()
        self.scanning = True
        self.generation += 1
        self.activity.emit("scan", True)
        def work():
            self.recovery.result()
            return scan_local(self.store, sources, self.scan_cancel,
                lambda n, size: self.status.emit(f"원본 {n:,}개 · {file_size(size)} 읽는 중…"), recursive)
        future = self.executor.submit(work)
        def done(result):
            self.scanning = False
            if self.closed:
                return
            try:
                report = result.result()
                self.status.emit(f"폴더 읽기 {'취소' if report['cancelled'] else '완료'}: {report['count']:,}개 · {file_size(report['bytes'])} · 임시 파일 제외 {report['skipped']:,}개")
                if report["errors"]:
                    self.error.emit("일부 파일 접근 실패:\n" + "\n".join(report["errors"][:8]))
            except Exception as error:
                self.error.emit(str(error))
            self.changed.emit()
            self.activity.emit("scan", False)
        future.add_done_callback(done)

    def refresh(self):
        if self.closed:
            return
        if self.refreshing:
            self.refresh_again = True
            return
        self.refreshing = True
        generation = self.generation
        def build():
            self.recovery.result()
            classifier = self.classifier()
            items = self.store.local_items()
            current = self.store.setting("local_active_scan")
            preview, queue = [], []
            for item in items:
                item["plan"] = classifier.classify(item["name"], item["manual_id"])
                item["duplicate_hint"] = "이력 있음 — 저장 전 다시 검사" if item["sha256"] else "내용 미확인 — 저장 시 SHA-256 검사"
                if current and item["last_scan"] == current:
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

    def start_downloads(self, plans=None, retry=False, mode="copy"):
        if self.downloading or self.scanning or self.indexing:
            self.error.emit("현재 작업을 완료하거나 일시정지한 뒤 시작하세요.")
            return
        self.download_cancel.clear()
        self.downloading = True
        self.activity.emit("download", True)
        def work():
            self.recovery.result()
            if plans is not None:
                self.store.enqueue_local(plans, mode)
            else:
                for item in self.store.local_items(["failed"] if retry else ["paused", "queued"]):
                    self.store.update(item["item_key"], phase="queued", error="")
            items = self.store.local_items(["queued"])
            self.batch_keys = {i["item_key"] for i in items}
            if not items:
                return
            folders = {i["folder"] for i in items}
            folders.update(c.folder for c in self.store.categories())
            folders.add(self.classifier().fallback)
            folders.update(self.store.setting("extra_folders", []))
            validate_locations(items, folders)
            self.status.emit("저장 폴더의 기존 파일 목록을 확인합니다…")
            report = self.store.index_folders([p for p in folders if Path(p).is_dir()], self.download_cancel,
                lambda n: self.status.emit(f"저장 폴더 기존 파일 {n:,}개 확인 중…"))
            if report["errors"]:
                raise OSError("중복 검사 폴더에 접근하지 못했습니다:\n" + "\n".join(report["errors"][:5]))
            LocalFileEngine(self.store, self.download_cancel, self.file_progress.emit, self.changed.emit).run()
        future = self.executor.submit(work)
        def done(result):
            self.downloading = False
            if self.closed:
                return
            try:
                result.result()
                self.status.emit("일시정지됨 — 대기열에서 재개할 수 있습니다." if self.download_cancel.is_set()
                    else "분류 처리 완료 — 완료·중복·실패 상태와 실제 저장 경로를 확인하세요.")
            except Exception as error:
                for item in self.store.local_items(["queued"]):
                    self.store.update(item["item_key"], phase="paused", error=str(error))
                self.error.emit(str(error))
            self.changed.emit()
            self.activity.emit("download", False)
        future.add_done_callback(done)
