import asyncio

import pytest

from utils.fast_telethon import CHUNK_SIZE, _atomic_finalize_sync, _load_meta, fast_download_file
from test_fast_telethon import MockClient, MockInputLocation


def test_engine_finalizer_never_replaces_an_existing_file(tmp_path):
    target, partial = tmp_path / "existing.bin", tmp_path / "download.part"
    target.write_bytes(b"user original")
    partial.write_bytes(b"new content")
    with pytest.raises(FileExistsError):
        _atomic_finalize_sync(str(partial), str(target))
    assert target.read_bytes() == b"user original"
    assert partial.read_bytes() == b"new content"


@pytest.mark.asyncio
async def test_short_network_chunk_cannot_be_finalized(tmp_path):
    target = tmp_path / "incomplete.bin"
    client = MockClient([], {0: b"short", CHUNK_SIZE: b"X" * CHUNK_SIZE})
    with pytest.raises(OSError, match="incomplete"):
        await fast_download_file(client, MockInputLocation(), str(target), CHUNK_SIZE * 2, dc_id=1, workers=2)
    assert not target.exists()


def test_corrupt_resume_indices_do_not_fake_complete_download(tmp_path):
    meta = tmp_path / "bad.meta"
    meta.write_text('{"file_size":1048576,"total_parts":2,"completed_parts":[-1,9]}')
    assert _load_meta(str(meta), CHUNK_SIZE * 2, 2) == set()
