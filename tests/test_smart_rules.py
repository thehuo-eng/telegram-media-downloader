import unicodedata

import pytest

from smart.rules import Category, Classifier, FileFilter, extensions, safe_filename


@pytest.fixture
def classifier(tmp_path):
    cats = [Category("회로", str(tmp_path / "회로"), ["회로", "circuit", "ch09"], priority=0),
            Category("전자기", str(tmp_path / "전자기"), ["ampere", "전자기", "회로"], priority=1),
            Category("영상", str(tmp_path / "영상"), extensions=["mp4", "mkv"], priority=2)]
    return Classifier(cats, str(tmp_path / "미분류"))


@pytest.mark.parametrize("name,expected", [
    ("회로이론_9장.pdf", "회로"), ("CIRCUIT_lecture03.mp4", "회로"),
    ("lecture_ch09.txt", "회로"), ("전자기학_기출2025.pdf", "전자기"),
    ("unmatched.pdf", "미분류"), ("lecture.MKV", "영상"),
    (unicodedata.normalize("NFD", "회로이론.pdf"), "회로")])
def test_keywords_case_unicode_or_and_extension(classifier, name, expected):
    assert classifier.classify(name).category == expected


def test_conflict_priority_and_manual_override(classifier):
    result = classifier.classify("회로.pdf")
    assert result.category == "회로"
    assert result.conflicts == ("전자기",)
    manual = classifier.categories[1].id
    result = classifier.classify("회로.pdf", manual)
    assert result.category == "전자기" and result.rule == "사용자 수동 지정"
    classifier.categories[0].priority = 9
    reordered = Classifier(classifier.categories, classifier.fallback)
    assert reordered.classify("회로.pdf").category == "전자기"


def test_global_filter_before_category_filter(tmp_path):
    cat = Category("PDF 회로", str(tmp_path), ["회로"], ["pdf"])
    rules = Classifier([cat], str(tmp_path / "미분류"))
    assert rules.classify("회로.pdf").category == cat.name
    assert rules.classify("회로.mp4").category == "미분류"
    rules.file_filter = FileFilter(["이미지"])
    assert not rules.classify("회로.pdf", cat.id).allowed


def test_default_disabled_and_deleted_manual(tmp_path):
    default = Category("기본", str(tmp_path), is_default=True)
    rules = Classifier([default], str(tmp_path / "미분류"))
    assert rules.classify("example.dat").category == "기본"
    default.enabled = False
    assert rules.classify("example.dat").category == "미분류"
    assert "삭제된" in rules.classify("example.dat", "deleted-id").rule


def test_extra_other_no_extension():
    assert FileFilter(["확장자 없음"]).allows("README")
    assert not FileFilter(["확장자 없음"]).allows("report.pdf")
    assert FileFilter([], ["psd"]).allows("design.PSD")
    assert FileFilter(["기타"]).allows("design.dwg")
    assert not FileFilter(["기타"]).allows("music.mp3")
    assert extensions("*.PDF, .hwpx\nMP4") == ["pdf", "hwpx", "mp4"]
    with pytest.raises(ValueError):
        extensions("../pdf")


@pytest.mark.parametrize("name", ["../CON.pdf", "NUL.txt", "con", "LPT1.tar.gz", "회로<>:?*.pdf", "C:\\secret\\test.pdf", "..", "\x00bad\n.pdf", "가" * 500 + ".pdf"])
def test_safe_windows_names(name):
    result = safe_filename(name)
    assert not any(ch in result for ch in '<>:"/\\|?*\x00\n')
    assert result not in (".", "..", "")
    assert not result.endswith((".", " "))
    assert len(result.encode("utf-16-le")) <= 360
    assert result.split(".")[0].upper() not in ("CON", "NUL", "LPT1")
