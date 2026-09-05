from __future__ import annotations

import io
import math

import pytest

from checkwash.cli import _WORKTREE_SEARCH_CHUNK, _stream_contains_any


class _RecordingBytesIO(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


@pytest.mark.parametrize(
    ("needle", "near_miss"),
    [
        (b"ababababac", b"ababababab"),
        (b"\x00\xffliteral\x00", b"\x00\xffliteram\x00"),
    ],
)
def test_stream_search_is_exact_across_chunk_boundary(
    needle: bytes,
    near_miss: bytes,
) -> None:
    prefix = b"x" * (_WORKTREE_SEARCH_CHUNK - 3)

    assert _stream_contains_any(io.BytesIO(prefix + needle), (needle,))
    assert not _stream_contains_any(io.BytesIO(prefix + near_miss), (needle,))


def test_stream_search_long_needle_crosses_adaptive_block_boundary() -> None:
    needle = b"BEGIN" + b"a" * (_WORKTREE_SEARCH_CHUNK * 8) + b"END"
    prefix = b"x" * (len(needle) - 3)
    stream = _RecordingBytesIO(prefix + needle + b"suffix")

    assert _stream_contains_any(stream, (b"not-present", needle))
    assert stream.read_sizes == [len(needle), len(needle)]


def test_stream_search_long_near_match_uses_linear_number_of_blocks() -> None:
    needle = b"a" * (_WORKTREE_SEARCH_CHUNK * 8) + b"b"
    data = b"a" * (len(needle) * 4) + b"c"
    stream = _RecordingBytesIO(data)

    assert not _stream_contains_any(stream, (needle,))
    assert len(stream.read_sizes) == math.ceil(len(data) / len(needle)) + 1
    assert set(stream.read_sizes) == {len(needle)}
