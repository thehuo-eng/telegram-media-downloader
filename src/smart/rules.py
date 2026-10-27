from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
import unicodedata
import uuid


FILE_GROUPS = {
    "문서": {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "hwp", "hwpx", "rtf", "csv", "epub", "md"},
    "동영상": {"mp4", "mkv", "avi", "mov", "wmv", "webm", "m4v", "mpeg", "mpg", "ts"},
    "이미지": {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic", "svg"},
    "오디오": {"mp3", "wav", "flac", "m4a", "ogg", "opus", "aac", "wma"},
    "압축파일": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz"},
}
KNOWN_EXTENSIONS = set().union(*FILE_GROUPS.values())


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text)).casefold()


def extensions(text: str | list[str]) -> list[str]:
    values = re.split(r"[,;\s]+", text) if isinstance(text, str) else text
    result = []
    for value in values:
        ext = normalized(value).strip().lstrip("*.")
        if ext and not re.fullmatch(r"[\w+-]+", ext):
            raise ValueError(f"확장자를 확인하세요: {value}")
        if ext and ext not in result:
            result.append(ext)
    return result


def extension(filename: str) -> str:
    return normalized(Path(filename.replace("\\", "/")).suffix).lstrip(".")


def safe_filename(name: str) -> str:
    # Treat Telegram names as plain text, never as relative or absolute paths.
    name = unicodedata.normalize("NFC", str(name))
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name).strip(" .") or "file"
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext, dot = name, "", ""
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", stem.split(".")[0].rstrip(" .")):
        stem = "_" + stem
    # Leave room for collision suffixes and NTFS's UTF-16 component limit.
    ext = ext[:24]
    suffix = dot + ext
    while len((stem + suffix).encode("utf-16-le")) > 360:
        stem = stem[:-1]
    return (stem + suffix).rstrip(" .") or "file"


def absolute_folder(folder: str) -> str:
    path = Path(folder).expanduser()
    if not path.is_absolute():
        raise ValueError("저장 폴더는 절대 경로로 지정하세요.")
    return str(path.resolve())


@dataclass
class Category:
    name: str
    folder: str
    keywords: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    enabled: bool = True
    priority: int = 0
    is_default: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def validate(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("범주 이름을 입력하세요.")
        self.folder = absolute_folder(self.folder)
        self.keywords = list(dict.fromkeys(k.strip() for k in self.keywords if k.strip()))
        self.extensions = extensions(self.extensions)
        return self

    def to_dict(self):
        return asdict(self)


@dataclass
class FileFilter:
    groups: list[str] = field(default_factory=lambda: list(FILE_GROUPS) + ["기타", "확장자 없음"])
    extra_extensions: list[str] = field(default_factory=list)

    def allows(self, filename: str) -> bool:
        ext = extension(filename)
        if not ext:
            return "확장자 없음" in self.groups
        if ext in self.extra_extensions:
            return True
        if "기타" in self.groups and ext not in KNOWN_EXTENSIONS:
            return True
        return any(ext in FILE_GROUPS.get(group, ()) for group in self.groups)


@dataclass(frozen=True)
class Classification:
    category_id: str | None
    category: str
    folder: str
    rule: str
    conflicts: tuple[str, ...] = ()
    allowed: bool = True


class Classifier:
    def __init__(self, categories: list[Category], fallback: str, file_filter: FileFilter | None = None):
        self.categories = sorted(categories, key=lambda c: (c.priority, c.id))
        self.fallback = absolute_folder(fallback)
        self.file_filter = file_filter or FileFilter()

    def classify(self, filename: str, manual_id: str | None = None) -> Classification:
        if not self.file_filter.allows(filename):
            return Classification(None, "제외", "", "전역 파일 형식 필터", allowed=False)
        enabled = [c for c in self.categories if c.enabled]
        manual = next((c for c in self.categories if c.id == manual_id), None)
        if manual:
            return Classification(manual.id, manual.name, manual.folder, "사용자 수동 지정")
        name, ext = normalized(filename), extension(filename)
        matches = []
        for cat in enabled:
            if cat.extensions and ext not in cat.extensions:
                continue
            hits = [kw for kw in cat.keywords if normalized(kw) in name]
            if hits:
                matches.append((cat, hits[0]))
        if matches:
            cat, keyword = matches[0]
            return Classification(cat.id, cat.name, cat.folder, f"키워드: {keyword}", tuple(c.name for c, _ in matches[1:]))
        ext_matches = [c for c in enabled if not c.keywords and ext in c.extensions]
        if ext_matches:
            cat = ext_matches[0]
            return Classification(cat.id, cat.name, cat.folder, f"확장자: .{ext}", tuple(c.name for c in ext_matches[1:]))
        default = next((c for c in enabled if c.is_default and not c.extensions), None)
        if default:
            return Classification(default.id, default.name, default.folder, "기본 범주")
        rule = "일치 규칙 없음" if not manual_id else "삭제된 수동 범주 — 미분류"
        return Classification(None, "미분류", self.fallback, rule)
