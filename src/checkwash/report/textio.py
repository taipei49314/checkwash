"""Encoding-safe human output; machine reports use their separate UTF-8 writer."""

from __future__ import annotations

import sys
import codecs


def write_text(text: str, stream=None) -> None:
    """Keep Unicode streams intact; visibly escape legacy output, never '?'.

    A legacy Windows Python pipe and its shell can disagree on their code page.
    ASCII escapes survive either decoder, including for glyphs cp1252 itself
    supports. StringIO and Unicode streams receive the original text.
    """
    if stream is None:
        stream = sys.stdout
    encoding = getattr(stream, "encoding", None)
    if encoding:
        try:
            normalized = codecs.lookup(encoding).name
        except LookupError:
            normalized = "ascii"
        if not normalized.startswith(("utf-8", "utf-16", "utf-32")):
            text = text.encode("ascii", errors="backslashreplace").decode("ascii")
        else:
            text = text.encode(encoding, errors="backslashreplace").decode(encoding)
    stream.write(text)
