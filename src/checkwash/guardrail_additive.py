"""Strict inert EOF-append classifier for repository-root `CLAUDE.md` (SPEC §4/§5, D-211, D-213).

An existing `CLAUDE.md` edit stays at `warn` (`GUARDRAIL_ADDITIVE`) only when it is a
strict inert append at end-of-file in linear time `O(N)`: `after` begins with the exact
unmodified `before` line sequence, at least one blank line separates `before`'s last
non-blank line from `added`'s first non-blank line, both sides end cleanly with no
unclosed fence or HTML block/comment/tag, frontmatter (both line-anchored YAML/TOML and
Claude Code `ni()`'s non-anchored `---` slice) is invariant, added lines carry no `---`
substring, no `3+` consecutive `` ` `` or `~`, no `<!--` or `-->`, and no `[label]:`
definition opener, and no NUL byte, invalid UTF-8, lone CR, non-LF Unicode line break, or
newly introduced `HIDDEN_UNICODE` / Unicode `Cf` / `Default_Ignorable_Code_Point`
character is present. Everything else fails closed (`False` -> `critical` under E4).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, deque
import re
import unicodedata

# Keep in lockstep with `engine._HIDDEN_CODEPOINTS` (SPEC §4 `HIDDEN_UNICODE`);
# we also reject any newly introduced Unicode `"Cf"` format character or Unicode
# `Default_Ignorable_Code_Point` (including Variation Selectors `U+FE00..U+FE0F`,
# `U+E0100..U+E01EF`, Hangul fillers `U+115F..U+1160`, `U+3164`, `U+FFA0`, and Tags).
_HIDDEN_CODEPOINTS: frozenset[int] = frozenset(
    [0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x00AD]
    + list(range(0x202A, 0x202F))
    + list(range(0x2066, 0x206A))
    + [0xFEFF]
)

# Claude Code 2.1.x `ni()` frontmatter stripper (`yx = /^---\s*\n([\s\S]*?)---\s*\n?/`),
# whose closing `---` is not line-anchored.
_CC_FRONTMATTER_RE = re.compile(r"^---\s*\n([\s\S]*?)---\s*\n?")

# Non-LF line/paragraph separators that `str.splitlines()` splits on.
_UNICODE_LINE_BREAKS: frozenset[str] = frozenset("\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")

# CommonMark §2.4 ASCII punctuation characters escapable by `\`.
_ASCII_PUNCTUATION: frozenset[str] = frozenset('!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~')

# CommonMark §4.6 Rule 1 block tags (can interrupt paragraphs and span blank lines
# until any line contains `</pre>`, `</script>`, `</style>`, or `</textarea>`).
_COMMONMARK_RULE1_TAGS: frozenset[str] = frozenset({
    "pre", "script", "style", "textarea",
})
_COMMONMARK_RULE1_CLOSERS: tuple[str, ...] = (
    "</pre>", "</script>", "</style>", "</textarea>",
)

# HTML5 §13.2.5 RAWTEXT / RCDATA / Script data elements whose interior does not
# parse normal HTML child tags (`<pre>` and `<listing>` stay in HTML5 Data state
# so inner tags like `<template>` ARE parsed by HTML5!).
_HTML5_RAW_TAGS: frozenset[str] = frozenset({
    "iframe", "noembed", "noframes", "noscript",
    "script", "style", "textarea", "title", "xmp",
})

# HTML5 void elements (never push onto the open element stack).
_VOID_HTML_TAGS: frozenset[str] = frozenset({
    "area", "base", "basefont", "bgsound", "br", "col", "command", "embed",
    "frame", "hr", "img", "input", "keygen", "link", "meta", "param",
    "source", "track", "wbr",
})

# HTML5 §13.2.6.3 implied-end-tag elements allowed to auto-close when an ancestor closes.
_IMPLIED_END_HTML_TAGS: frozenset[str] = frozenset({
    "dd", "dt", "li", "optgroup", "option", "p", "rb", "rp", "rt", "rtc",
})

# CommonMark §4.6 rule 6 block tags (62 names).
_COMMONMARK_TYPE6_TAGS: frozenset[str] = frozenset({
    "address", "article", "aside", "base", "basefont", "blockquote", "body",
    "caption", "center", "col", "colgroup", "dd", "details", "dialog", "dir",
    "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
    "frame", "frameset", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header",
    "hr", "html", "iframe", "legend", "li", "link", "main", "menu", "menuitem",
    "nav", "noframes", "ol", "optgroup", "option", "p", "param", "search",
    "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead",
    "title", "tr", "track", "ul",
})

# Standard HTML container / hiding / semantic tags tracked on the open tag stack
# even when written without attributes (bare `<path>` or `<env>` placeholders in
# prose without a matching `</env>` are NOT in this set and carry no attributes,
# so they stay plain prose).
_SIGNIFICANT_HTML_TAGS: frozenset[str] = (
    _COMMONMARK_TYPE6_TAGS
    | _COMMONMARK_RULE1_TAGS
    | _HTML5_RAW_TAGS
    | frozenset({
        "a", "abbr", "applet", "audio", "b", "bdi", "bdo", "button", "canvas",
        "cite", "code", "data", "datalist", "del", "dfn", "em", "font", "i", "ins",
        "kbd", "label", "listing", "map", "mark", "marquee", "math", "meter",
        "nobr", "object", "output", "picture", "plaintext", "portal", "progress",
        "q", "rb", "rp", "rt", "rtc", "ruby", "s", "samp", "select", "small",
        "span", "strike", "strong", "sub", "sup", "svg", "template", "time", "u",
        "var", "video",
    })
)

# HTML5 §13.2.5 tag-name / end-tag boundary delimiters.
_HTML_TAG_DELIMS: frozenset[str] = frozenset({" ", "\t", "\n", "\x0c", "/", ">"})
_HTML_WS: frozenset[str] = frozenset({" ", "\t", "\n", "\x0c"})

# HTML5 §13.2.5.32–40 attribute tokenizer states.
_ATTR_BEFORE_NAME = 0
_ATTR_NAME = 1
_ATTR_AFTER_NAME = 2
_ATTR_BEFORE_VALUE = 3
_ATTR_DQUOTE = 4
_ATTR_SQUOTE = 5
_ATTR_UNQUOTED = 6
_ATTR_SELF_CLOSING = 7


def _is_default_ignorable_non_cf(cp: int) -> bool:
    """Unicode `Default_Ignorable_Code_Point` ranges outside General_Category `Cf`."""
    return (
        cp == 0x034F
        or 0x115F <= cp <= 0x1160
        or 0x17B4 <= cp <= 0x17B5
        or 0x180B <= cp <= 0x180F
        or 0x2060 <= cp <= 0x206F
        or cp == 0x3164
        or 0xFE00 <= cp <= 0xFE0F
        or cp == 0xFFA0
        or 0xFFF0 <= cp <= 0xFFF8
        or 0xE0000 <= cp <= 0xE0FFF
    )


def _is_hidden_or_format_char(ch: str) -> bool:
    cp = ord(ch)
    if cp < 0xAD:
        return False
    return (
        cp in _HIDDEN_CODEPOINTS
        or _is_default_ignorable_non_cf(cp)
        or unicodedata.category(ch) == "Cf"
    )


def _split_lf_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def _is_ascii_alpha(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _is_tag_name_char(ch: str) -> bool:
    return _is_ascii_alpha(ch) or ("0" <= ch <= "9") or ch == "-"


def _is_cm66_attr_start(ch: str) -> bool:
    return _is_ascii_alpha(ch) or ch in ("_", ":")


def _is_cm66_attr_char(ch: str) -> bool:
    return _is_ascii_alpha(ch) or ("0" <= ch <= "9") or ch in ("_", ".", ":", "-")


def _collect_closing_tag_names(lines: list[str]) -> frozenset[str]:
    """Pre-scan `lines` in O(N) for all `</tag...>` names present anywhere in the document."""
    closed: set[str] = set()
    for line in lines:
        n = len(line)
        pos = 0
        while True:
            idx = line.find("</", pos)
            if idx == -1 or idx + 2 >= n:
                break
            if _is_ascii_alpha(line[idx + 2]):
                end_name = idx + 3
                while end_name < n and line[end_name] not in _HTML_TAG_DELIMS:
                    end_name += 1
                if end_name == n or line[end_name] in _HTML_TAG_DELIMS:
                    closed.add(line[idx + 2 : end_name].lower())
                pos = end_name
            else:
                pos = idx + 2
    return frozenset(closed)


def _detect_frontmatter_end(lines: list[str]) -> int | None:
    """Return closing line index if `lines` begins with a YAML/TOML frontmatter block."""
    if not lines:
        return None
    first = lines[0].rstrip(" \t")
    if first == "---":
        closers = ("---", "...")
    elif first == "+++":
        closers = ("+++",)
    else:
        return None
    for idx in range(1, len(lines)):
        if lines[idx].rstrip(" \t") in closers:
            return idx
    return None


def _thematic_break_suffix_bounds(line: str) -> tuple[int, int, int]:
    """Return `(last_non_ws_idx, tb_homog_start, tb_third_idx)` in O(L).

    Any non-whitespace suffix `line[idx:]` is a CommonMark §4.1 thematic break iff
    `tb_homog_start <= idx <= tb_third_idx`.
    """
    n = len(line)
    k = n - 1
    while k >= 0 and line[k] in (" ", "\t"):
        k -= 1
    last_non_ws = k
    if k < 0 or line[k] not in "-*_":
        return last_non_ws, n + 1, -1
    tchar = line[k]
    count = 0
    third_idx = -1
    while k >= 0 and line[k] in (tchar, " ", "\t"):
        if line[k] == tchar:
            count += 1
            if count == 3:
                third_idx = k
        k -= 1
    if count < 3:
        return last_non_ws, n + 1, -1
    return last_non_ws, k + 1, third_idx


def _is_thematic_break(s: str) -> bool:
    """CommonMark §4.1 thematic break on `s`."""
    if not s or s[0] not in "-*_":
        return False
    marker = s[0]
    count = 0
    for ch in s:
        if ch == marker:
            count += 1
        elif ch not in (" ", "\t"):
            return False
    return count >= 3


def _is_atx_heading(s: str) -> bool:
    """CommonMark §4.2 ATX heading (`1..6` `#` followed by space, tab, or EOL)."""
    if not s or s[0] != "#":
        return False
    n = len(s)
    hashes = 0
    while hashes < n and hashes < 7 and s[hashes] == "#":
        hashes += 1
    if hashes > 6:
        return False
    return hashes == n or s[hashes] in (" ", "\t")


def _is_setext_underline(s: str) -> bool:
    """CommonMark §4.3 Setext heading underline (`=+` or `-+` plus optional trailing spaces/tabs)."""
    if not s or s[0] not in ("=", "-"):
        return False
    ch = s[0]
    i = 0
    n = len(s)
    while i < n and s[i] == ch:
        i += 1
    while i < n and s[i] in (" ", "\t"):
        i += 1
    return i == n


def _split_unescaped_pipes(s: str) -> tuple[list[str], int]:
    """Split `s.strip(' \\t')` into GFM table cells on unescaped `|` and return `(cells, unescaped_pipe_count)`."""
    trimmed = s.strip(" \t")
    if not trimmed:
        return [], 0
    cells: list[str] = []
    pipes = 0
    start = 0
    i = 0
    n = len(trimmed)
    while i < n:
        ch = trimmed[i]
        if ch == "\\" and i + 1 < n and trimmed[i + 1] in _ASCII_PUNCTUATION:
            i += 2
            continue
        if ch == "|":
            pipes += 1
            cells.append(trimmed[start:i])
            start = i + 1
        i += 1
    cells.append(trimmed[start:])
    if len(cells) >= 2 and cells[0] == "":
        cells.pop(0)
    if len(cells) >= 1 and trimmed.endswith("|") and cells[-1] == "":
        bs = 0
        k = n - 2
        while k >= 0 and trimmed[k] == "\\":
            bs += 1
            k -= 1
        if bs % 2 == 0:
            cells.pop()
    return cells, pipes


def _gfm_table_cell_count(s: str, *, is_delimiter: bool) -> int | None:
    """Return GFM §4.10 (`cmark-gfm`) cell count for a header or delimiter row, or `None` if invalid."""
    cells, pipes = _split_unescaped_pipes(s)
    if not cells:
        return None
    if not is_delimiter:
        return len(cells)
    if pipes == 0:
        return None
    for cell in cells:
        c = cell.strip(" \t")
        if not c:
            return None
        if c.startswith(":"):
            c = c[1:]
        if c.endswith(":"):
            c = c[:-1]
        if not c or any(ch != "-" for ch in c):
            return None
    return len(cells)


def _scan_ws(line: str, pos: int, base_col: int, virt_sp: int) -> tuple[int, int]:
    """Measure indentation columns from `(pos, base_col, virt_sp)` using true 4-column tab stops."""
    col = base_col + virt_sp
    n = len(line)
    while pos < n:
        ch = line[pos]
        if ch == " ":
            col += 1
            pos += 1
        elif ch == "\t":
            col += 4 - (col % 4)
            pos += 1
        else:
            break
    return col - base_col, pos


def _consume_cols(
    line: str,
    pos: int,
    base_col: int,
    virt_sp: int,
    width: int,
) -> tuple[int, int, int]:
    """Consume `width` indentation columns from `(pos, base_col, virt_sp)` with 4-column tab stops."""
    take_v = min(virt_sp, width)
    base_col += take_v
    virt_sp -= take_v
    rem = width - take_v
    while rem > 0:
        ch = line[pos]
        if ch == " ":
            pos += 1
            base_col += 1
            rem -= 1
        else:
            step = 4 - (base_col % 4)
            pos += 1
            if step <= rem:
                base_col += step
                rem -= step
            else:
                base_col += rem
                virt_sp = step - rem
                rem = 0
    return pos, base_col, virt_sp


def _try_match_one_bq(
    line: str,
    pos: int,
    base_col: int,
    virt_sp: int,
) -> tuple[int, int, int] | None:
    """If `<= 3` columns of indentation precede `>`, consume `>` + optional 1 space/tab column."""
    n = len(line)
    col = base_col + virt_sp
    p = pos
    while p < n:
        ch = line[p]
        if ch == " ":
            if col - base_col + 1 > 3:
                return None
            col += 1
            p += 1
        elif ch == "\t":
            step = 4 - (col % 4)
            if col - base_col + step > 3:
                return None
            col += step
            p += 1
        else:
            break
    if p >= n or line[p] != ">":
        return None
    gt_end_col = col + 1
    p += 1
    if p < n and line[p] == " ":
        return p + 1, gt_end_col + 1, 0
    if p < n and line[p] == "\t":
        step = 4 - (gt_end_col % 4)
        return p + 1, gt_end_col + 1, step - 1
    return p, gt_end_col, 0


def _match_open_containers(
    line: str,
    last_non_ws: int,
    containers: list[tuple[str, int, int]],
    bq_positions: list[int],
) -> tuple[int, int, int, int]:
    """CommonMark Appendix A Step 1: match open `("bq", 0, _)` and `("list", w, _)` prefixes in O(L)."""
    total_open = len(containers)
    if total_open == 0:
        return 0, 0, 0, 0
    if last_non_ws < 0 and not bq_positions:
        return total_open, len(line), 0, 0

    pos = 0
    base_col = 0
    virt_sp = 0
    matched = 0
    last_bq = bq_positions[-1] if bq_positions else -1
    cached_ws_pos = -1
    cached_end_col = 0

    while matched < total_open:
        kind, width, _ = containers[matched]
        if kind == "bq":
            res = _try_match_one_bq(line, pos, base_col, virt_sp)
            if res is None:
                break
            pos, base_col, virt_sp = res
            cached_ws_pos = -1
            matched += 1
        else:
            if pos > last_non_ws:
                if last_bq < matched:
                    return total_open, len(line), base_col, 0
                idx_pos = bisect_right(bq_positions, matched - 1)
                return bq_positions[idx_pos], len(line), base_col, 0
            if cached_ws_pos < 0:
                lead_col, cached_ws_pos = _scan_ws(line, pos, base_col, virt_sp)
                cached_end_col = base_col + lead_col
            else:
                lead_col = cached_end_col - base_col
            if cached_ws_pos > last_non_ws:
                if last_bq < matched:
                    return total_open, len(line), cached_end_col, 0
                idx_pos = bisect_right(bq_positions, matched - 1)
                return bq_positions[idx_pos], len(line), cached_end_col, 0
            if lead_col < width:
                break
            pos, base_col, virt_sp = _consume_cols(line, pos, base_col, virt_sp, width)
            matched += 1

    return matched, pos, base_col, virt_sp


def _parse_new_containers(
    line: str,
    pos: int,
    base_col: int,
    virt_sp: int,
    last_non_ws: int,
    tb_homog_start: int,
    tb_third_idx: int,
    *,
    in_paragraph: bool,
) -> tuple[list[tuple[str, int]], int, str]:
    """CommonMark Appendix A Step 2: scan newly opened interleaved `>` and list markers in O(L)."""
    n = len(line)
    new_containers: list[tuple[str, int]] = []
    cur_pos = pos
    cur_col = base_col
    cur_virt = virt_sp

    while True:
        lead_col, idx = _scan_ws(line, cur_pos, cur_col, cur_virt)
        if lead_col > 3 or idx > last_non_ws:
            eff_indent = 0 if idx > last_non_ws else lead_col
            eff_pos = n if idx > last_non_ws else idx
            break

        if line[idx] == ">":
            gt_end_abs = cur_col + lead_col + 1
            p = idx + 1
            if p < n and line[p] == " ":
                cur_pos = p + 1
                cur_col = gt_end_abs + 1
                cur_virt = 0
            elif p < n and line[p] == "\t":
                step = 4 - (gt_end_abs % 4)
                cur_pos = p + 1
                cur_col = gt_end_abs + 1
                cur_virt = step - 1
            else:
                cur_pos = p
                cur_col = gt_end_abs
                cur_virt = 0
            new_containers.append(("bq", 0))
            in_paragraph = False
            continue

        if tb_homog_start <= idx <= tb_third_idx:
            eff_indent = lead_col
            eff_pos = idx
            break

        marker_len = 0
        is_ordered = False
        ordered_val_is_one = False
        ch0 = line[idx]
        if ch0 in "-+*":
            if idx + 1 == n or line[idx + 1] in (" ", "\t"):
                marker_len = 1
        elif "0" <= ch0 <= "9":
            d = idx
            limit_d = min(n, idx + 9)
            while d < limit_d and "0" <= line[d] <= "9":
                d += 1
            if d < n and line[d] in (".", ")"):
                if d + 1 == n or line[d + 1] in (" ", "\t"):
                    marker_len = (d - idx) + 1
                    is_ordered = True
                    ordered_val_is_one = line[idx:d].lstrip("0") == "1"

        if marker_len == 0:
            eff_indent = lead_col
            eff_pos = idx
            break

        after_marker_pos = idx + marker_len
        if in_paragraph:
            if after_marker_pos > last_non_ws or (is_ordered and not ordered_val_is_one):
                eff_indent = lead_col
                eff_pos = idx
                break

        marker_end_abs = cur_col + lead_col + marker_len
        if after_marker_pos > last_non_ws:
            new_containers.append(("list", (marker_end_abs + 1) - cur_col))
            eff_indent = 0
            eff_pos = n
            break

        sp_col, sp_pos = _scan_ws(line, after_marker_pos, marker_end_abs, 0)
        if sp_col > 4:
            new_containers.append(("list", (marker_end_abs + 1) - cur_col))
            eff_indent = sp_col - 1
            eff_pos = sp_pos
            break

        new_containers.append(("list", (marker_end_abs + sp_col) - cur_col))
        cur_pos = sp_pos
        cur_col = marker_end_abs + sp_col
        cur_virt = 0
        in_paragraph = False

    eff_stripped = line[eff_pos:] if eff_pos < n else ""
    return new_containers, eff_indent, eff_stripped


def _match_fence_opener(eff_indent: int, eff_stripped: str) -> tuple[str, int] | None:
    """Return `(fence_char, fence_len)` if `eff_stripped` opens a CommonMark §4.5 code fence."""
    if eff_indent > 3 or len(eff_stripped) < 3:
        return None
    ch = eff_stripped[0]
    if ch == "`":
        run = len(eff_stripped) - len(eff_stripped.lstrip("`"))
        if run >= 3 and "`" not in eff_stripped[run:]:
            return ("`", run)
    elif ch == "~":
        run = len(eff_stripped) - len(eff_stripped.lstrip("~"))
        if run >= 3:
            return ("~", run)
    return None


# CommonMark Phase-1 HTML block kind: `"rule1"`, `("rule25", end_seq)`, or `"rule67"`.
_CmHtmlBlock = str | tuple[str, str]


def _match_cm_html_block_1_to_5(eff_indent: int, eff_stripped: str) -> _CmHtmlBlock | None:
    """Detect exact CommonMark 0.31.2 §4.6 rules 1–5 Phase-1 HTML block openers."""
    if eff_indent > 3 or len(eff_stripped) < 2 or eff_stripped[0] != "<":
        return None
    if eff_stripped.startswith("<!--"):
        return ("rule25", "-->")
    if eff_stripped.startswith("<?"):
        return ("rule25", "?>")
    if eff_stripped.startswith("<![CDATA["):
        return ("rule25", "]]>")
    if len(eff_stripped) >= 3 and eff_stripped[1] == "!" and _is_ascii_alpha(eff_stripped[2]):
        return ("rule25", ">")
    if _is_ascii_alpha(eff_stripped[1]):
        end_name = 2
        n = len(eff_stripped)
        while end_name < n and _is_tag_name_char(eff_stripped[end_name]):
            end_name += 1
        if end_name == n or eff_stripped[end_name] in (" ", "\t", ">"):
            tag = eff_stripped[1:end_name].lower()
            if tag in _COMMONMARK_RULE1_TAGS:
                return "rule1"
    return None


def _cm_rule1_ends_on_line(subline: str) -> bool:
    """CommonMark §4.6 Rule 1 end condition: line contains `</pre>`, `</script>`, `</style>`, or `</textarea>`."""
    if "</" not in subline:
        return False
    low = subline.lower()
    return any(tok in low for tok in _COMMONMARK_RULE1_CLOSERS)


def _is_complete_cm66_single_line_tag(trimmed: str) -> bool:
    """Return True iff `trimmed` is a single complete CommonMark §6.6 open tag (non-Rule-1) or close tag."""
    n = len(trimmed)
    if n < 3 or trimmed[0] != "<" or trimmed[-1] != ">":
        return False
    if trimmed[1] == "/":
        if not _is_ascii_alpha(trimmed[2]):
            return False
        end_name = 3
        while end_name < n - 1 and _is_tag_name_char(trimmed[end_name]):
            end_name += 1
        return trimmed[end_name:-1].strip(" \t") == ""

    if not _is_ascii_alpha(trimmed[1]):
        return False
    end_name = 2
    while end_name < n - 1 and _is_tag_name_char(trimmed[end_name]):
        end_name += 1
    tag_lower = trimmed[1:end_name].lower()
    if tag_lower in _COMMONMARK_RULE1_TAGS:
        return False
    p = end_name
    while p < n:
        ws_end = p
        while ws_end < n and trimmed[ws_end] in (" ", "\t"):
            ws_end += 1
        if ws_end == n - 1 and trimmed[ws_end] == ">":
            return True
        if ws_end == n - 2 and trimmed[ws_end:] == "/>":
            return True
        if ws_end == p or ws_end >= n or not _is_cm66_attr_start(trimmed[ws_end]):
            return False
        attr_end = ws_end + 1
        while attr_end < n and _is_cm66_attr_char(trimmed[attr_end]):
            attr_end += 1
        eq_pos = attr_end
        while eq_pos < n and trimmed[eq_pos] in (" ", "\t"):
            eq_pos += 1
        if eq_pos < n and trimmed[eq_pos] == "=":
            val_pos = eq_pos + 1
            while val_pos < n and trimmed[val_pos] in (" ", "\t"):
                val_pos += 1
            if val_pos >= n - 1:
                return False
            vc = trimmed[val_pos]
            if vc in ('"', "'"):
                q_end = trimmed.find(vc, val_pos + 1)
                if q_end == -1 or q_end >= n - 1:
                    return False
                p = q_end + 1
            else:
                u_end = val_pos
                while u_end < n - 1 and trimmed[u_end] not in (" ", "\t", '"', "'", "=", "<", ">", "`"):
                    u_end += 1
                if u_end == val_pos:
                    return False
                p = u_end
        else:
            p = attr_end
    return False


def _is_type6_or_type7_html_block_line(
    eff_indent: int,
    eff_stripped: str,
    *,
    in_paragraph: bool,
) -> bool:
    """Detect exact CommonMark 0.31.2 §4.6 rule 6 & rule 7 HTML block openers."""
    if eff_indent > 3 or len(eff_stripped) < 3 or eff_stripped[0] != "<":
        return False
    idx = 1
    if eff_stripped[idx] == "/":
        idx += 1
    if idx >= len(eff_stripped) or not _is_ascii_alpha(eff_stripped[idx]):
        return False
    end_name = idx + 1
    while end_name < len(eff_stripped) and _is_tag_name_char(eff_stripped[end_name]):
        end_name += 1
    tag = eff_stripped[idx:end_name].lower()

    if tag in _COMMONMARK_TYPE6_TAGS:
        if end_name == len(eff_stripped):
            return True
        nxt = eff_stripped[end_name]
        if nxt in (" ", "\t", ">") or eff_stripped.startswith("/>", end_name):
            return True

    if in_paragraph:
        return False
    return _is_complete_cm66_single_line_tag(eff_stripped.rstrip(" \t"))


def _consume_link_ref_defs(para_texts: list[str]) -> int:
    """Return how many leading lines of `para_texts` are consumed by CommonMark §4.7 link reference definitions."""
    if not para_texts:
        return 0
    joined = "\n".join(para_texts)
    n = len(joined)
    line_starts: list[int] = [0]
    for idx, ch in enumerate(joined):
        if ch == "\n":
            line_starts.append(idx + 1)

    def _offset_to_line(off: int) -> int:
        return bisect_right(line_starts, off) - 1

    pos = 0
    consumed_lines = 0
    while pos < n:
        col = 0
        p = pos
        while p < n and joined[p] in (" ", "\t"):
            step = 1 if joined[p] == " " else 4 - (col % 4)
            if col + step > 3:
                p = -1
                break
            col += step
            p += 1
        if p == -1 or p >= n or joined[p] != "[":
            break

        lbl_start = p + 1
        j = lbl_start
        limit = min(n, lbl_start + 1000)
        found_ket = -1
        while j < limit:
            ch = joined[j]
            if ch == "\\" and j + 1 < limit and joined[j + 1] in _ASCII_PUNCTUATION:
                j += 2
                continue
            if ch == "[":
                break
            if ch == "]":
                found_ket = j
                break
            j += 1
        if found_ket == -1 or found_ket + 1 >= n or joined[found_ket + 1] != ":":
            break
        if joined[lbl_start:found_ket].strip(" \t\n") == "":
            break

        d = found_ket + 2
        saw_nl = False
        while d < n and joined[d] in (" ", "\t", "\n"):
            if joined[d] == "\n":
                if saw_nl:
                    break
                saw_nl = True
            d += 1
        if d >= n or joined[d] == "\n":
            break

        if joined[d] == "<":
            k = d + 1
            dest_end = -1
            while k < n:
                ch = joined[k]
                if ch == "\\" and k + 1 < n and joined[k + 1] in _ASCII_PUNCTUATION:
                    k += 2
                    continue
                if ch in ("\n", "<"):
                    break
                if ch == ">":
                    dest_end = k + 1
                    break
                k += 1
            if dest_end == -1:
                break
        else:
            k = d
            parens = 0
            while k < n:
                ch = joined[k]
                if ch == "\\" and k + 1 < n and joined[k + 1] in _ASCII_PUNCTUATION:
                    k += 2
                    continue
                if ch in (" ", "\t", "\n") or ord(ch) < 0x20 or ord(ch) == 0x7F:
                    break
                if ch == "(":
                    parens += 1
                    if parens > 32:
                        parens = -1
                        break
                elif ch == ")":
                    if parens == 0:
                        parens = -1
                        break
                    parens -= 1
                k += 1
            if parens != 0 or k == d:
                break
            dest_end = k

        t = dest_end
        while t < n and joined[t] in (" ", "\t"):
            t += 1
        dest_ends_line = t == n or joined[t] == "\n"
        best_end_offset = t if dest_ends_line else -1

        sep = dest_end
        sep_nl = False
        while sep < n and joined[sep] in (" ", "\t", "\n"):
            if joined[sep] == "\n":
                if sep_nl:
                    break
                sep_nl = True
            sep += 1

        if sep > dest_end and sep < n and joined[sep] in ('"', "'", "("):
            opener = joined[sep]
            closer = ")" if opener == "(" else opener
            q = sep + 1
            title_end = -1
            while q < n:
                ch = joined[q]
                if ch == "\\" and q + 1 < n and joined[q + 1] in _ASCII_PUNCTUATION:
                    q += 2
                    continue
                if opener == "(" and ch == "(":
                    break
                if ch == closer:
                    title_end = q + 1
                    break
                q += 1
            if title_end != -1:
                u = title_end
                while u < n and joined[u] in (" ", "\t"):
                    u += 1
                if u == n or joined[u] == "\n":
                    best_end_offset = u

        if best_end_offset == -1:
            break

        end_line = _offset_to_line(max(p, best_end_offset - 1))
        consumed_lines = end_line + 1
        if best_end_offset >= n:
            break
        pos = best_end_offset + 1

    return consumed_lines


def _is_autolink(text: str, lt_pos: int) -> int | None:
    """If `text[lt_pos:]` starts a CommonMark §6.5 single-line URI or email autolink, return index past `>`."""
    n = len(text)
    limit = min(n, lt_pos + 256)
    k = lt_pos + 1
    end = -1
    while k < limit:
        ch = text[k]
        if ch == ">":
            end = k
            break
        if ch in (" ", "\t", "\n", "<") or ord(ch) <= 0x20:
            return None
        k += 1
    if end == -1 or end == lt_pos + 1:
        return None
    inner = text[lt_pos + 1 : end]
    if ":" in inner:
        scheme, rest = inner.split(":", 1)
        if 2 <= len(scheme) <= 32 and _is_ascii_alpha(scheme[0]) and rest:
            if all(_is_ascii_alpha(c) or ("0" <= c <= "9") or c in "+.-" for c in scheme):
                return end + 1
    if "@" in inner and not inner.startswith("@") and not inner.endswith("@"):
        local, domain = inner.split("@", 1)
        if local and domain and "@" not in domain and "." in domain:
            return end + 1
    return None


class _HtmlStackState:
    """Amortized O(1) open-HTML-element stack with trie-interned integer state IDs."""

    def __init__(self, trie: dict[tuple[int, str], int]) -> None:
        self._trie = trie
        self.stack: list[tuple[str, int]] = []
        self.counts: Counter[str] = Counter()
        self.state_id: int = 0
        self.unmatched_closes: int = 0

    def push(self, tag: str) -> None:
        key = (self.state_id, tag)
        nxt = self._trie.get(key)
        if nxt is None:
            nxt = len(self._trie) + 1
            self._trie[key] = nxt
        self.stack.append((tag, self.state_id))
        self.counts[tag] += 1
        self.state_id = nxt

    def pop(self, tag: str) -> bool:
        if self.counts[tag] <= 0:
            self.unmatched_closes += 1
            return False
        idx = len(self.stack) - 1
        while idx >= 0 and self.stack[idx][0] != tag:
            if self.stack[idx][0] not in _IMPLIED_END_HTML_TAGS:
                self.push("\x00mismatch")
                return False
            idx -= 1
        if idx < 0:
            self.unmatched_closes += 1
            return False
        while len(self.stack) > idx:
            top_tag, prev_id = self.stack.pop()
            self.counts[top_tag] -= 1
            self.state_id = prev_id
        return True


def _is_self_closing_html_tag(
    tag_lower: str,
    slash_before_gt: bool,
    html_state: _HtmlStackState,
) -> bool:
    """HTML5 §13.2.5: `/>` only self-closes void elements and foreign `<svg>`/`<math>` elements."""
    if tag_lower in _VOID_HTML_TAGS:
        return True
    if not slash_before_gt:
        return False
    return (
        tag_lower in ("svg", "math")
        or html_state.counts["svg"] > 0
        or html_state.counts["math"] > 0
    )


def _should_track_html_tag(
    tag_lower: str,
    had_attrs: bool,
    closed_tags: frozenset[str],
) -> bool:
    return (
        tag_lower not in _VOID_HTML_TAGS
        and (had_attrs or tag_lower in _SIGNIFICANT_HTML_TAGS or tag_lower in closed_tags)
    )


# `(tag_lower, attr_state, had_attrs)` — `tag_lower` may be `"div"`, `"/div"`, or `"\x00raw_close"`.
_UnclosedHtml5Tag = tuple[str, int, bool]


def _step_html5_attr_char(state: int, c: str, had_attrs: bool) -> tuple[int, bool]:
    """Advance one non-`>` character in the HTML5 §13.2.5.32–40 attribute state machine."""
    if state == _ATTR_DQUOTE:
        if c == '"':
            return _ATTR_BEFORE_NAME, had_attrs
        return _ATTR_DQUOTE, had_attrs
    if state == _ATTR_SQUOTE:
        if c == "'":
            return _ATTR_BEFORE_NAME, had_attrs
        return _ATTR_SQUOTE, had_attrs

    if state == _ATTR_SELF_CLOSING:
        state = _ATTR_BEFORE_NAME

    if state == _ATTR_BEFORE_NAME:
        if c in _HTML_WS:
            return _ATTR_BEFORE_NAME, had_attrs
        if c == "/":
            return _ATTR_SELF_CLOSING, had_attrs
        return _ATTR_NAME, True

    if state == _ATTR_NAME:
        if c in _HTML_WS:
            return _ATTR_AFTER_NAME, had_attrs
        if c == "/":
            return _ATTR_SELF_CLOSING, had_attrs
        if c == "=":
            return _ATTR_BEFORE_VALUE, had_attrs
        return _ATTR_NAME, True

    if state == _ATTR_AFTER_NAME:
        if c in _HTML_WS:
            return _ATTR_AFTER_NAME, had_attrs
        if c == "/":
            return _ATTR_SELF_CLOSING, had_attrs
        if c == "=":
            return _ATTR_BEFORE_VALUE, had_attrs
        return _ATTR_NAME, True

    if state == _ATTR_BEFORE_VALUE:
        if c in _HTML_WS:
            return _ATTR_BEFORE_VALUE, had_attrs
        if c == '"':
            return _ATTR_DQUOTE, True
        if c == "'":
            return _ATTR_SQUOTE, True
        return _ATTR_UNQUOTED, True

    # `_ATTR_UNQUOTED`
    if c in _HTML_WS:
        return _ATTR_BEFORE_NAME, had_attrs
    return _ATTR_UNQUOTED, True


def _advance_html5_tag_attrs(
    text: str,
    start: int,
    unclosed_tag: _UnclosedHtml5Tag,
    html_state: _HtmlStackState,
    closed_tags: frozenset[str],
    *,
    append_newline_at_end: bool,
    unmatched_sink: list[str] | None = None,
) -> tuple[int | None, _UnclosedHtml5Tag | None, str | None]:
    """Scan HTML5 §13.2.5.32–40 tag attributes from `start` until unquoted `>` or end of `text` in O(L).

    Returns `(resume_pos, next_unclosed_tag, opened_raw_mode)`.
    """
    tag_lower, state, had_attrs = unclosed_tag
    j = start
    n = len(text)
    while j < n:
        c = text[j]
        if state not in (_ATTR_DQUOTE, _ATTR_SQUOTE) and c == ">":
            slash_before_gt = state == _ATTR_SELF_CLOSING
            if tag_lower == "\x00raw_close":
                return j + 1, None, None
            if tag_lower.startswith("/"):
                close_name = tag_lower[1:]
                if close_name not in _VOID_HTML_TAGS and (
                    close_name in _SIGNIFICANT_HTML_TAGS
                    or close_name in closed_tags
                    or html_state.counts[close_name] > 0
                ):
                    if not html_state.pop(close_name) and unmatched_sink is not None:
                        unmatched_sink.append(f"unmatched_close:{close_name}")
                return j + 1, None, None

            self_closing = _is_self_closing_html_tag(tag_lower, slash_before_gt, html_state)
            if not self_closing and tag_lower == "plaintext":
                return j + 1, None, "plaintext"
            if not self_closing and tag_lower in _HTML5_RAW_TAGS:
                return j + 1, None, tag_lower
            if not self_closing and _should_track_html_tag(tag_lower, had_attrs, closed_tags):
                html_state.push(tag_lower)
            return j + 1, None, None

        state, had_attrs = _step_html5_attr_char(state, c, had_attrs)
        j += 1

    if append_newline_at_end:
        state, had_attrs = _step_html5_attr_char(state, "\n", had_attrs)
    return None, (tag_lower, state, had_attrs), None


def _advance_script_raw(
    text: str,
    start: int,
    script_state: int,
    *,
    eol_is_delim: bool,
) -> tuple[int | None, int]:
    """Advance HTML5 §13.2.5.4–30 `<script>` 3-state machine (`0` normal, `1` `<!--`, `2` `<script` double-escaped) in strict O(L).

    Returns `(after_end_script_name_pos, next_script_state)`. When `after_end_script_name_pos`
    is not `None`, `</script` + delimiter matched in state `0` or `1`, so the caller
    transitions to `("\x00raw_close", _ATTR_BEFORE_NAME, False)` at that index.
    """
    n = len(text)
    pos = start
    state = script_state
    arrow_cache: int | None = None

    while pos < n:
        lt = text.find("<", pos)
        if state != 0:
            if arrow_cache is None or (arrow_cache != -1 and arrow_cache < pos):
                arrow_cache = text.find("-->", pos)
            arrow = arrow_cache
        else:
            arrow = -1

        if lt == -1 and arrow == -1:
            return None, state
        if arrow != -1 and (lt == -1 or arrow < lt):
            state = 0
            pos = arrow + 3
            continue

        if lt + 1 >= n:
            return None, state
        nxt = text[lt + 1]
        if nxt == "!":
            if state == 0 and text.startswith("<!--", lt):
                state = 1
                pos = lt + 4
                continue
        elif nxt == "/":
            if lt + 8 <= n and text[lt : lt + 8].lower() == "</script":
                has_delim = (lt + 8 == n and eol_is_delim) or (
                    lt + 8 < n and text[lt + 8] in _HTML_TAG_DELIMS
                )
                if has_delim:
                    if state in (0, 1):
                        return lt + 8, 0
                    # `state == 2`: HTML5 §13.2.5.29 drops back to state `1` without closing `<script>`.
                    state = 1
                    pos = min(n, lt + 9)
                    continue
        elif nxt in ("s", "S"):
            if state == 1 and lt + 7 <= n and text[lt : lt + 7].lower() == "<script":
                has_delim = (lt + 7 == n and eol_is_delim) or (
                    lt + 7 < n and text[lt + 7] in _HTML_TAG_DELIMS
                )
                if has_delim:
                    state = 2
                    pos = min(n, lt + 8)
                    continue

        pos = lt + 1

    return None, state


def _advance_nonscript_raw(
    text: str,
    text_lower: str,
    start: int,
    tag_lower: str,
    html_state: _HtmlStackState,
    *,
    eol_is_delim: bool,
) -> int | None:
    """Advance HTML5 RAWTEXT / RCDATA (`style`, `textarea`, `title`, `noscript`, etc.) in O(L).

    Returns `after_end_tag_name_pos` when `</{tag_lower}` + delimiter matches, or `None`.
    """
    prefix = f"</{tag_lower}"
    plen = len(prefix)
    n = len(text)
    search_pos = start
    while search_pos < n:
        found = text_lower.find(prefix, search_pos)
        if found == -1:
            if tag_lower == "noscript" and text.find("<", start) != -1:
                html_state.push("\x00noscript_lt")
            return None
        after_p = found + plen
        has_delim = (after_p == n and eol_is_delim) or (
            after_p < n and text[after_p] in _HTML_TAG_DELIMS
        )
        if has_delim:
            if tag_lower == "noscript" and text.find("<", start, found) != -1:
                html_state.push("\x00noscript_lt")
            return after_p
        search_pos = after_p
    if tag_lower == "noscript" and text.find("<", start) != -1:
        html_state.push("\x00noscript_lt")
    return None


def _feed_html5_chunk(
    text: str,
    html_state: _HtmlStackState,
    closed_tags: frozenset[str],
    raw_mode: str | None,
    unclosed_tag: _UnclosedHtml5Tag | None,
    script_state: int,
    *,
    eol_is_delim: bool,
    unmatched_sink: list[str] | None = None,
) -> tuple[str | None, _UnclosedHtml5Tag | None, int]:
    """Feed raw HTML `text` into the stateful HTML5 §13.2.5 tokenizer in strict O(L)."""
    pos = 0
    n = len(text)
    text_lower: str | None = None

    while pos <= n:
        if unclosed_tag is not None:
            resume, unclosed_tag, opened_raw = _advance_html5_tag_attrs(
                text,
                pos,
                unclosed_tag,
                html_state,
                closed_tags,
                append_newline_at_end=eol_is_delim,
                unmatched_sink=unmatched_sink,
            )
            if opened_raw is not None:
                raw_mode = opened_raw
                script_state = 0
            if resume is None:
                return raw_mode, unclosed_tag, script_state
            pos = resume
            continue

        if raw_mode is not None:
            if raw_mode == "plaintext":
                return "plaintext", None, 0

            if raw_mode == "comment":
                c1 = text.find("-->", pos)
                c2 = text.find("--!>", pos)
                if c1 == -1 and c2 == -1:
                    return "comment", None, 0
                if c2 != -1 and (c1 == -1 or c2 < c1):
                    # HTML5 §13.2.5.49 closes comment at `--!>` even though CommonMark Rule 2 waits for `-->`.
                    html_state.push("\x00comment_bang_desync")
                    pos = c2 + 4
                else:
                    pos = c1 + 3
                raw_mode = None
                continue

            if raw_mode == "cdata_foreign":
                end_cd = text.find("]]>", pos)
                if end_cd == -1:
                    return "cdata_foreign", None, 0
                pos = end_cd + 3
                raw_mode = None
                continue

            if raw_mode == "cdata_html":
                gt = text.find(">", pos)
                end_cd = text.find("]]>", pos)
                if gt == -1:
                    return "cdata_html", None, 0
                if end_cd == -1 or gt < end_cd + 2:
                    html_state.push("\x00bogus_cdata_desync")
                    pos = gt + 1
                else:
                    pos = end_cd + 3
                raw_mode = None
                continue

            if raw_mode == "pi":
                gt = text.find(">", pos)
                end_pi = text.find("?>", pos)
                if gt == -1:
                    return "pi", None, 0
                if end_pi == -1 or gt < end_pi + 1:
                    html_state.push("\x00bogus_pi_desync")
                    pos = gt + 1
                else:
                    pos = end_pi + 2
                raw_mode = None
                continue

            if raw_mode == "decl":
                gt = text.find(">", pos)
                if gt == -1:
                    return "decl", None, 0
                pos = gt + 1
                raw_mode = None
                continue

            if raw_mode == "script":
                after_end, script_state = _advance_script_raw(
                    text, pos, script_state, eol_is_delim=eol_is_delim,
                )
                if after_end is None:
                    return "script", None, script_state
                raw_mode = None
                script_state = 0
                unclosed_tag = ("\x00raw_close", _ATTR_BEFORE_NAME, False)
                pos = after_end
                continue

            # Non-script `_HTML5_RAW_TAGS`.
            if text_lower is None:
                text_lower = text.lower()
            after_end = _advance_nonscript_raw(
                text, text_lower, pos, raw_mode, html_state, eol_is_delim=eol_is_delim,
            )
            if after_end is None:
                return raw_mode, None, 0
            raw_mode = None
            unclosed_tag = ("\x00raw_close", _ATTR_BEFORE_NAME, False)
            pos = after_end
            continue

        if pos >= n:
            return None, None, 0

        lt = text.find("<", pos)
        if lt == -1 or lt + 1 >= n:
            return None, None, 0

        nxt = text[lt + 1]
        if nxt == "!":
            if text.startswith("<!-->", lt):
                pos = lt + 5
                continue
            if text.startswith("<!--->", lt):
                pos = lt + 6
                continue
            if text.startswith("<!--", lt):
                raw_mode = "comment"
                pos = lt + 4
                continue
            if text.startswith("<![CDATA[", lt):
                if html_state.counts["svg"] > 0 or html_state.counts["math"] > 0:
                    raw_mode = "cdata_foreign"
                else:
                    raw_mode = "cdata_html"
                pos = lt + 9
                continue
            raw_mode = "decl"
            pos = lt + 2
            continue

        if nxt == "?":
            raw_mode = "pi"
            pos = lt + 2
            continue

        if nxt == "/":
            if lt + 2 >= n:
                return ("decl", None, 0) if eol_is_delim else (None, None, 0)
            if text[lt + 2] == ">":
                pos = lt + 3
                continue
            if _is_ascii_alpha(text[lt + 2]):
                end_name = lt + 3
                while end_name < n and text[end_name] not in _HTML_TAG_DELIMS:
                    end_name += 1
                tag_lower = text[lt + 2 : end_name].lower()
                unclosed_tag = (f"/{tag_lower}", _ATTR_BEFORE_NAME, False)
                pos = end_name
                continue
            raw_mode = "decl"
            pos = lt + 2
            continue

        if _is_ascii_alpha(nxt):
            end_name = lt + 2
            while end_name < n and text[end_name] not in _HTML_TAG_DELIMS:
                end_name += 1
            tag_lower = text[lt + 1 : end_name].lower()
            unclosed_tag = (tag_lower, _ATTR_BEFORE_NAME, False)
            pos = end_name
            continue

        pos = lt + 1

    return raw_mode, unclosed_tag, script_state


def _scan_markdown_inlines(
    text: str,
    line_tags: list[list[str]],
    line_html_ids: list[int],
    html_state: _HtmlStackState,
    closed_tags: frozenset[str],
) -> tuple[str | None, _UnclosedHtml5Tag | None, int]:
    """Scan CommonMark Phase-2 inlines in strict O(P) and feed emitted §6.6 Raw HTML chunks into HTML5."""
    if line_html_ids:
        line_html_ids[0] = html_state.state_id
    n = len(text)
    if n == 0:
        return None, None, 0

    line_ends: list[int] = []
    for idx, ch in enumerate(text):
        if ch == "\n":
            line_ends.append(idx)
    line_ends.append(n)

    cur_ln = 0
    raw_mode: str | None = None
    unclosed_tag: _UnclosedHtml5Tag | None = None
    script_state = 0

    def _advance_ln(offset: int) -> int:
        nonlocal cur_ln
        while cur_ln < len(line_ends) - 1 and offset > line_ends[cur_ln]:
            cur_ln += 1
            if cur_ln < len(line_html_ids):
                line_html_ids[cur_ln] = html_state.state_id
                if raw_mode is not None or unclosed_tag is not None:
                    line_tags[cur_ln].append(f"raw:{raw_mode or 'tag'}")
        return cur_ln

    def _ln_of(offset: int) -> int:
        ln = cur_ln
        while ln < len(line_ends) - 1 and offset > line_ends[ln]:
            ln += 1
        return ln

    runs_by_len: dict[int, deque[int]] = {}
    if "`" in text:
        idx = 0
        while idx < n:
            if text[idx] == "`":
                end_bt = idx + 1
                while end_bt < n and text[end_bt] == "`":
                    end_bt += 1
                runs_by_len.setdefault(end_bt - idx, deque()).append(idx)
                idx = end_bt
            else:
                idx += 1

    # Sorted quote-offset & failure-offset caches guaranteeing exact lookup in O(P log P).
    dquote_positions: list[int] | None = None
    squote_positions: list[int] | None = None
    failed_cm66_pos: set[int] = set()

    def _find_dquote(q_start: int) -> int:
        nonlocal dquote_positions
        if dquote_positions is None:
            dquote_positions = [idx_q for idx_q, ch_q in enumerate(text) if ch_q == '"']
        idx_q = bisect_left(dquote_positions, q_start)
        return dquote_positions[idx_q] if idx_q < len(dquote_positions) else -1

    def _find_squote(q_start: int) -> int:
        nonlocal squote_positions
        if squote_positions is None:
            squote_positions = [idx_q for idx_q, ch_q in enumerate(text) if ch_q == "'"]
        idx_q = bisect_left(squote_positions, q_start)
        return squote_positions[idx_q] if idx_q < len(squote_positions) else -1

    def _match_cm66_open_tag_end(end_name: int) -> tuple[int | None, bool]:
        """Return `(gt_pos, poisoned_unclosed)` for CommonMark §6.6 open tag starting at `end_name`."""
        if end_name == n:
            return None, True
        if text[end_name] not in (" ", "\t", "\n", "/", ">"):
            return None, False

        visited: list[int] = []
        p = end_name
        while p < n:
            if p in failed_cm66_pos:
                failed_cm66_pos.update(visited)
                return None, False
            visited.append(p)
            ws_end = p
            while ws_end < n and text[ws_end] in (" ", "\t", "\n"):
                ws_end += 1
            if ws_end == n:
                return None, True
            c = text[ws_end]
            if c == ">":
                return ws_end, False
            if c == "/":
                if ws_end + 1 == n:
                    return None, True
                if text[ws_end + 1] == ">":
                    return ws_end + 1, False
                failed_cm66_pos.update(visited)
                return None, False
            if ws_end == p or not _is_cm66_attr_start(c):
                failed_cm66_pos.update(visited)
                return None, False

            attr_end = ws_end + 1
            while attr_end < n and _is_cm66_attr_char(text[attr_end]):
                attr_end += 1
            eq_pos = attr_end
            while eq_pos < n and text[eq_pos] in (" ", "\t", "\n"):
                eq_pos += 1
            if eq_pos < n and text[eq_pos] == "=":
                val_pos = eq_pos + 1
                while val_pos < n and text[val_pos] in (" ", "\t", "\n"):
                    val_pos += 1
                if val_pos == n:
                    return None, True
                vc = text[val_pos]
                if vc == '"':
                    q_end = _find_dquote(val_pos + 1)
                    if q_end == -1:
                        return None, True
                    p = q_end + 1
                elif vc == "'":
                    q_end = _find_squote(val_pos + 1)
                    if q_end == -1:
                        return None, True
                    p = q_end + 1
                else:
                    u_end = val_pos
                    while u_end < n and text[u_end] not in (" ", "\t", "\n", "\x0c", '"', "'", "=", "<", ">", "`"):
                        u_end += 1
                    if u_end == val_pos:
                        failed_cm66_pos.update(visited)
                        return None, False
                    p = u_end
            else:
                p = attr_end

        return None, True

    def _emit_raw_chunk(open_ln: int, close_ln: int, chunk: str, kind_prefix: str) -> None:
        nonlocal raw_mode, unclosed_tag, script_state
        if close_ln > open_ln:
            line_tags[open_ln].append(f"{kind_prefix}_open")
            for mid in range(open_ln + 1, close_ln):
                line_tags[mid].append(kind_prefix)
            line_tags[close_ln].append(f"{kind_prefix}_close")
        unmatched_here: list[str] = []
        raw_mode, unclosed_tag, script_state = _feed_html5_chunk(
            chunk,
            html_state,
            closed_tags,
            raw_mode,
            unclosed_tag,
            script_state,
            eol_is_delim=False,
            unmatched_sink=unmatched_here,
        )
        if unmatched_here:
            line_tags[close_ln].extend(unmatched_here)
        if unclosed_tag is not None:
            html_state.push("\x00desync_inline_mid_tag")
            unclosed_tag = None

    i = 0
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
            _advance_ln(i + 1)
            i += 2
            continue

        if ch == "`":
            open_ln = _advance_ln(i)
            end_bt = i + 1
            while end_bt < n and text[end_bt] == "`":
                end_bt += 1
            k = end_bt - i
            q = runs_by_len.get(k)
            if q is not None:
                while q and q[0] <= i:
                    q.popleft()
            if q:
                close_pos = q.popleft()
                close_ln = _ln_of(close_pos)
                if close_ln > open_ln:
                    line_tags[open_ln].append("bt_open")
                    for mid in range(open_ln + 1, close_ln):
                        line_tags[mid].append("bt_mid")
                    line_tags[close_ln].append("bt_close")
                i = close_pos + k
                _advance_ln(i - 1)
            else:
                i = end_bt
            continue

        if ch == "<":
            open_ln = _advance_ln(i)

            # 1. CommonMark §6.6 HTML comment `<!-- ... -->` (including `<!-->` and `<!--->`).
            if text.startswith("<!--", i):
                if text.startswith("<!-->", i):
                    _emit_raw_chunk(open_ln, open_ln, "<!-->", "comment")
                    i += 5
                    continue
                if text.startswith("<!--->", i):
                    _emit_raw_chunk(open_ln, open_ln, "<!--->", "comment")
                    i += 6
                    continue
                close_pos = text.find("-->", i + 4)
                if close_pos == -1:
                    html_state.push("\x00unclosed_inline_comment")
                    line_tags[open_ln].append("comment_open")
                    for mid in range(open_ln + 1, len(line_tags)):
                        line_tags[mid].append("comment")
                    return "comment", None, 0
                close_ln = _ln_of(close_pos)
                _emit_raw_chunk(open_ln, close_ln, text[i : close_pos + 3], "comment")
                i = close_pos + 3
                _advance_ln(i - 1)
                continue

            # 2. CommonMark §6.6 CDATA `<![CDATA[ ... ]]>`.
            if text.startswith("<![CDATA[", i):
                close_pos = text.find("]]>", i + 9)
                if close_pos == -1:
                    html_state.push("\x00unclosed_inline_cdata")
                    line_tags[open_ln].append("comment_open")
                    for mid in range(open_ln + 1, len(line_tags)):
                        line_tags[mid].append("comment")
                    return "cdata_html", None, 0
                close_ln = _ln_of(close_pos)
                _emit_raw_chunk(open_ln, close_ln, text[i : close_pos + 3], "comment")
                i = close_pos + 3
                _advance_ln(i - 1)
                continue

            # 3. CommonMark §6.6 processing instruction `<? ... ?>`.
            if text.startswith("<?", i):
                close_pos = text.find("?>", i + 2)
                if close_pos == -1:
                    html_state.push("\x00unclosed_inline_pi")
                    line_tags[open_ln].append("comment_open")
                    for mid in range(open_ln + 1, len(line_tags)):
                        line_tags[mid].append("comment")
                    return "pi", None, 0
                close_ln = _ln_of(close_pos)
                _emit_raw_chunk(open_ln, close_ln, text[i : close_pos + 2], "comment")
                i = close_pos + 2
                _advance_ln(i - 1)
                continue

            # 4. CommonMark §6.6 declaration `<!` + ASCII letter .. `>`.
            if i + 2 < n and text[i + 1] == "!" and _is_ascii_alpha(text[i + 2]):
                close_pos = text.find(">", i + 2)
                if close_pos == -1:
                    html_state.push("\x00unclosed_inline_decl")
                    line_tags[open_ln].append("comment_open")
                    for mid in range(open_ln + 1, len(line_tags)):
                        line_tags[mid].append("comment")
                    return "decl", None, 0
                close_ln = _ln_of(close_pos)
                _emit_raw_chunk(open_ln, close_ln, text[i : close_pos + 1], "comment")
                i = close_pos + 1
                _advance_ln(i - 1)
                continue

            # 5. CommonMark §6.5 single-line URI / email autolink (`<= 255` chars, O(1)).
            auto_end = _is_autolink(text, i)
            if auto_end is not None:
                i = auto_end
                continue

            # 6. CommonMark §6.6 closing tag `^</[A-Za-z][A-Za-z0-9-]*\s*>`.
            if i + 2 < n and text[i + 1] == "/" and _is_ascii_alpha(text[i + 2]):
                end_name = i + 3
                while end_name < n and _is_tag_name_char(text[end_name]):
                    end_name += 1
                j = end_name
                while j < n and text[j] in (" ", "\t", "\n"):
                    j += 1
                if j == n:
                    html_state.push("\x00unclosed_inline_tag")
                    line_tags[open_ln].append("tag_attr_open")
                    for mid in range(open_ln + 1, len(line_tags)):
                        line_tags[mid].append("tag_attr")
                    return None, ("/unclosed", _ATTR_BEFORE_NAME, False), 0
                if text[j] == ">":
                    gt_ln = _ln_of(j)
                    _emit_raw_chunk(open_ln, gt_ln, text[i : j + 1], "tag_attr")
                    i = j + 1
                    _advance_ln(i - 1)
                    continue
                i += 1
                continue

            # 7. CommonMark §6.6 opening tag.
            if i + 1 < n and _is_ascii_alpha(text[i + 1]):
                end_name = i + 2
                while end_name < n and _is_tag_name_char(text[end_name]):
                    end_name += 1
                gt_pos, poisoned_unclosed = _match_cm66_open_tag_end(end_name)
                if poisoned_unclosed:
                    html_state.push("\x00unclosed_inline_tag")
                    line_tags[open_ln].append("tag_attr_open")
                    for mid in range(open_ln + 1, len(line_tags)):
                        line_tags[mid].append("tag_attr")
                    return None, ("unclosed", _ATTR_BEFORE_NAME, True), 0
                if gt_pos is not None:
                    gt_ln = _ln_of(gt_pos)
                    _emit_raw_chunk(open_ln, gt_ln, text[i : gt_pos + 1], "tag_attr")
                    i = gt_pos + 1
                    _advance_ln(i - 1)
                    continue

        i += 1

    _advance_ln(n)
    return raw_mode, unclosed_tag, script_state


def _annotate_markdown_lines(
    lines: list[str],
    html_trie: dict[tuple[int, str], int],
    container_trie: dict[tuple[int, str], int],
) -> tuple[
    list[tuple[str, str]],
    list[str] | None,
    bool,
    tuple[tuple[str, int], ...],
    int,
]:
    """Pair each line with its structural Markdown / HTML / frontmatter context in O(N)."""
    total = len(lines)
    states: list[str] = [""] * total
    fm_end = _detect_frontmatter_end(lines)
    fm_lines: list[str] | None = None
    start_idx = 0
    if fm_end is not None:
        fm_lines = lines[: fm_end + 1]
        states[0] = "frontmatter_open"
        for idx in range(1, fm_end):
            states[idx] = "frontmatter"
        states[fm_end] = "frontmatter_close"
        start_idx = fm_end + 1

    closed_tags = _collect_closing_tag_names(lines[start_idx:])
    html_state = _HtmlStackState(html_trie)

    # Active open container stack: `(kind, width, prev_c_id)` + sorted indices of `"bq"` entries.
    containers: list[tuple[str, int, int]] = []
    bq_positions: list[int] = []
    c_id = 0

    def _truncate_containers(keep: int) -> None:
        nonlocal c_id
        if keep < len(containers):
            c_id = containers[keep][2]
            del containers[keep:]
            while bq_positions and bq_positions[-1] >= keep:
                bq_positions.pop()

    def _push_containers(new_items: list[tuple[str, int]]) -> None:
        nonlocal c_id
        for kind, width in new_items:
            token = "bq" if kind == "bq" else f"L{width}"
            key = (c_id, token)
            nxt = container_trie.get(key)
            if nxt is None:
                nxt = len(container_trie) + 1
                container_trie[key] = nxt
            if kind == "bq":
                bq_positions.append(len(containers))
            containers.append((kind, width, c_id))
            c_id = nxt

    fence: tuple[str, int, int] | None = None
    cm_html_block: _CmHtmlBlock | None = None
    raw_mode: str | None = None
    unclosed_tag: _UnclosedHtml5Tag | None = None
    script_state = 0

    para_indices: list[int] = []
    para_texts: list[str] = []
    para_c_id = 0

    def _poison_and_reset_html5_mid_state(reason: str) -> None:
        nonlocal raw_mode, unclosed_tag, script_state
        if raw_mode is not None or unclosed_tag is not None:
            html_state.push(reason)
            raw_mode = None
            unclosed_tag = None
            script_state = 0

    def _flush_paragraph(
        *,
        setext_idx: int | None = None,
        setext_stripped: str = "",
        setext_c_id: int = 0,
    ) -> None:
        nonlocal para_indices, para_texts, para_c_id
        if not para_indices:
            if setext_idx is not None:
                if _is_thematic_break(setext_stripped):
                    states[setext_idx] = f"thematic_break|c:{setext_c_id}|h:{html_state.state_id}"
                else:
                    para_c_id = setext_c_id
                    para_indices = [setext_idx]
                    para_texts = [setext_stripped]
            return

        link_ref_count = _consume_link_ref_defs(para_texts)
        for k in range(link_ref_count):
            states[para_indices[k]] = f"link_ref|c:{para_c_id}|h:{html_state.state_id}"

        rem_indices = para_indices[link_ref_count:]
        rem_texts = para_texts[link_ref_count:]
        flushed_c_id = para_c_id
        para_indices = []
        para_texts = []

        if not rem_indices:
            if setext_idx is not None:
                if _is_thematic_break(setext_stripped):
                    states[setext_idx] = f"thematic_break|c:{setext_c_id}|h:{html_state.state_id}"
                else:
                    para_c_id = setext_c_id
                    para_indices = [setext_idx]
                    para_texts = [setext_stripped]
            return

        row_kinds = ["prose"] * len(rem_indices)
        if setext_idx is None:
            for t in range(len(rem_texts) - 1):
                delim_cols = _gfm_table_cell_count(rem_texts[t + 1], is_delimiter=True)
                if delim_cols is not None:
                    hdr_cols = _gfm_table_cell_count(rem_texts[t], is_delimiter=False)
                    if hdr_cols == delim_cols:
                        row_kinds[t] = "table_header"
                        row_kinds[t + 1] = "table_delim"
                        for r in range(t + 2, len(rem_texts)):
                            row_kinds[r] = "table_row"
                        break

        line_tags: list[list[str]] = [[] for _ in rem_indices]
        line_html_ids: list[int] = [html_state.state_id] * len(rem_indices)
        p_raw, p_unclosed, _ = _scan_markdown_inlines(
            "\n".join(rem_texts),
            line_tags,
            line_html_ids,
            html_state,
            closed_tags,
        )
        if p_raw is not None or p_unclosed is not None:
            html_state.push("\x00desync_inline_end")

        if setext_idx is not None:
            row_kinds = ["setext_heading"] * len(rem_indices)
            states[setext_idx] = f"setext_underline|c:{flushed_c_id}|h:{html_state.state_id}"

        for idx_in_rem, line_idx in enumerate(rem_indices):
            extras = ",".join(line_tags[idx_in_rem])
            tag_part = f"|{extras}" if extras else ""
            states[line_idx] = (
                f"{row_kinds[idx_in_rem]}|c:{flushed_c_id}|h:{line_html_ids[idx_in_rem]}{tag_part}"
            )

    for idx in range(start_idx, total):
        line = lines[idx]
        last_non_ws, tb_homog_start, tb_third_idx = _thematic_break_suffix_bounds(line)
        matched, pos, base_col, virt_sp = _match_open_containers(
            line, last_non_ws, containers, bq_positions,
        )
        rel_col, non_ws_pos = _scan_ws(line, pos, base_col, virt_sp)
        is_blank_after_matched = non_ws_pos > last_non_ws
        after_matched_stripped = line[non_ws_pos:] if not is_blank_after_matched else ""

        # A. Open fenced code block: check container exit BEFORE testing closing fence.
        if fence is not None:
            fchar, flen, f_h = fence
            if matched < len(containers):
                fence = None
            else:
                if is_blank_after_matched:
                    states[idx] = f"code|c:{c_id}|h:{f_h}"
                    continue
                if (
                    rel_col <= 3
                    and len(after_matched_stripped) >= flen
                    and after_matched_stripped[0] == fchar
                ):
                    run = len(after_matched_stripped) - len(after_matched_stripped.lstrip(fchar))
                    if run >= flen and after_matched_stripped[run:].strip(" \t") == "":
                        fence = None
                        states[idx] = f"fence_close:{fchar}|c:{c_id}|h:{f_h}"
                        continue
                states[idx] = f"code|c:{c_id}|h:{f_h}"
                continue

        # B. Open CommonMark §4.6 Phase-1 HTML block (`rule1`, `rule25`, or `rule67`).
        if cm_html_block is not None:
            if matched < len(containers):
                _poison_and_reset_html5_mid_state("\x00desync_container_html")
                cm_html_block = None
            elif cm_html_block == "rule67" and is_blank_after_matched:
                _poison_and_reset_html5_mid_state("\x00desync_rule67_blank")
                cm_html_block = None
            else:
                subline = line[pos:]
                entry_h = html_state.state_id
                if unclosed_tag is not None:
                    kind_lbl = "tag_attr"
                elif cm_html_block == "rule67" and raw_mode is None:
                    kind_lbl = "html_block"
                else:
                    kind_lbl = "comment"
                raw_mode, unclosed_tag, script_state = _feed_html5_chunk(
                    subline,
                    html_state,
                    closed_tags,
                    raw_mode,
                    unclosed_tag,
                    script_state,
                    eol_is_delim=True,
                )
                if cm_html_block == "rule1" and _cm_rule1_ends_on_line(subline):
                    _poison_and_reset_html5_mid_state("\x00desync_rule1_end")
                    cm_html_block = None
                elif isinstance(cm_html_block, tuple) and cm_html_block[1] in subline:
                    _poison_and_reset_html5_mid_state("\x00desync_rule25_end")
                    cm_html_block = None
                states[idx] = f"{kind_lbl}|c:{c_id}|h:{entry_h}"
                continue

        # Blank line after matched containers.
        if is_blank_after_matched:
            _flush_paragraph()
            _truncate_containers(matched)
            states[idx] = f"blank|bq:{len(bq_positions)}|h:{html_state.state_id}"
            continue

        # Non-blank line: scan any newly opened interleaved `>` and list markers.
        new_containers, eff_indent, eff_stripped = _parse_new_containers(
            line,
            pos,
            base_col,
            virt_sp,
            last_non_ws,
            tb_homog_start,
            tb_third_idx,
            in_paragraph=bool(para_indices),
        )
        has_new_containers = bool(new_containers)

        # D1. CommonMark §4.5 fenced code block opener.
        fence_spec = _match_fence_opener(eff_indent, eff_stripped)
        if fence_spec is not None:
            _flush_paragraph()
            _truncate_containers(matched)
            _push_containers(new_containers)
            fchar, flen = fence_spec
            f_h = html_state.state_id
            fence = (fchar, flen, f_h)
            states[idx] = f"fence_open:{fchar}|c:{c_id}|h:{f_h}"
            continue

        # D2. CommonMark §4.6 rules 1–5 Phase-1 HTML blocks.
        cm15 = _match_cm_html_block_1_to_5(eff_indent, eff_stripped)
        if cm15 is not None:
            _flush_paragraph()
            _truncate_containers(matched)
            _push_containers(new_containers)
            entry_h = html_state.state_id
            raw_mode, unclosed_tag, script_state = _feed_html5_chunk(
                eff_stripped,
                html_state,
                closed_tags,
                None,
                None,
                0,
                eol_is_delim=True,
            )
            if cm15 == "rule1" and _cm_rule1_ends_on_line(eff_stripped):
                _poison_and_reset_html5_mid_state("\x00desync_rule1_end")
                cm_html_block = None
            elif isinstance(cm15, tuple) and cm15[1] in eff_stripped:
                _poison_and_reset_html5_mid_state("\x00desync_rule25_end")
                cm_html_block = None
            else:
                cm_html_block = cm15
            states[idx] = f"comment|c:{c_id}|h:{entry_h}"
            continue

        # E. CommonMark §4.2 ATX heading (`# ...`).
        if eff_indent <= 3 and _is_atx_heading(eff_stripped):
            _flush_paragraph()
            _truncate_containers(matched)
            _push_containers(new_containers)
            entry_h = html_state.state_id
            h_tags: list[list[str]] = [[]]
            h_ids: list[int] = [entry_h]
            h_raw, h_unclosed, _ = _scan_markdown_inlines(
                eff_stripped,
                h_tags,
                h_ids,
                html_state,
                closed_tags,
            )
            if h_raw is not None or h_unclosed is not None:
                html_state.push("\x00desync_inline_end")
            states[idx] = f"atx_heading|c:{c_id}|h:{entry_h}"
            continue

        # F. CommonMark §4.3 Setext heading underline (`===` / `---`, cannot be lazy).
        if (
            para_indices
            and matched == len(containers)
            and not has_new_containers
            and eff_indent <= 3
            and _is_setext_underline(eff_stripped)
        ):
            _flush_paragraph(
                setext_idx=idx,
                setext_stripped=eff_stripped,
                setext_c_id=c_id,
            )
            continue

        # G. CommonMark §4.1 thematic break (`---`, `***`, `___`, including inside list/blockquote).
        if eff_indent <= 3 and _is_thematic_break(eff_stripped):
            _flush_paragraph()
            _truncate_containers(matched)
            _push_containers(new_containers)
            states[idx] = f"thematic_break|c:{c_id}|h:{html_state.state_id}"
            continue

        # H. CommonMark §4.6 Type 6 / Type 7 HTML block opener.
        if _is_type6_or_type7_html_block_line(
            eff_indent,
            eff_stripped,
            in_paragraph=(bool(para_indices) and not has_new_containers),
        ):
            _flush_paragraph()
            _truncate_containers(matched)
            _push_containers(new_containers)
            entry_h = html_state.state_id
            raw_mode, unclosed_tag, script_state = _feed_html5_chunk(
                eff_stripped,
                html_state,
                closed_tags,
                None,
                None,
                0,
                eol_is_delim=True,
            )
            cm_html_block = "rule67"
            states[idx] = f"html_block|c:{c_id}|h:{entry_h}"
            continue

        # I. Newly opened container(s) (`>` or list marker) starting prose, indented code, or empty item.
        if has_new_containers:
            _flush_paragraph()
            _truncate_containers(matched)
            _push_containers(new_containers)
            if eff_stripped == "":
                if new_containers[-1][0] == "bq":
                    states[idx] = f"blank|bq:{len(bq_positions)}|h:{html_state.state_id}"
                else:
                    states[idx] = f"list_empty|c:{c_id}|h:{html_state.state_id}"
            elif eff_indent >= 4:
                states[idx] = f"indented_code|c:{c_id}|h:{html_state.state_id}"
            else:
                para_c_id = c_id
                para_indices = [idx]
                para_texts = [eff_stripped]
            continue

        # J. Indented code block (`>= 4` columns beyond matched containers when no paragraph is open).
        if not para_indices:
            _truncate_containers(matched)
            if eff_indent >= 4:
                states[idx] = f"indented_code|c:{c_id}|h:{html_state.state_id}"
                continue
            para_c_id = c_id
            para_indices = [idx]
            para_texts = [eff_stripped]
            continue

        # K. Paragraph continuation (including CommonMark §5.1 / §5.2 lazy continuation).
        para_indices.append(idx)
        para_texts.append(after_matched_stripped)

    _flush_paragraph()
    eof_clean = (
        fence is None
        and cm_html_block not in ("rule1",)
        and not isinstance(cm_html_block, tuple)
        and (cm_html_block != "rule67" or not html_state.stack)
        and raw_mode is None
        and unclosed_tag is None
        and not any(tag.startswith("\x00") for tag, _ in html_state.stack)
    )
    return (
        [(lines[i], states[i]) for i in range(total)],
        fm_lines,
        eof_clean,
        tuple(html_state.stack),
        html_state.unmatched_closes,
    )


def _cc_frontmatter_split(text: str) -> tuple[bool, str, str]:
    """Split leading `--- ... ---` with Claude Code `ni()`'s non-anchored regex."""
    m = _CC_FRONTMATTER_RE.match(text)
    if m is None:
        return False, "", text
    return True, m.group(0), text[m.end() :]


def _strip_bq_and_list_prefixes(line: str) -> str:
    n = len(line)
    p = 0
    while p < n:
        while p < n and line[p] in (" ", "\t"):
            p += 1
        if p >= n:
            return ""
        if line[p] == ">":
            p += 1
            continue
        if line[p] in "-+*" and (p + 1 == n or line[p + 1] in (" ", "\t")):
            p += 1
            continue
        if "0" <= line[p] <= "9":
            d = p
            while d < min(n, p + 9) and "0" <= line[d] <= "9":
                d += 1
            if d < n and line[d] in (".", ")") and (d + 1 == n or line[d + 1] in (" ", "\t")):
                p = d + 1
                continue
        break
    return line[p:]


def _has_link_ref_opener(added_lines: list[str]) -> bool:
    """Return True in O(N) if `added_lines` opens any `[label]:` or `[^footnote]:` definition."""
    if not any("]:" in line for line in added_lines):
        return False
    in_label = False
    for raw_line in added_lines:
        stripped = _strip_bq_and_list_prefixes(raw_line)
        if not stripped:
            in_label = False
            continue
        i = 0
        n = len(stripped)
        if not in_label:
            if stripped[0] != "[":
                continue
            in_label = True
            i = 1
        while i < n:
            ch = stripped[i]
            if ch == "\\" and i + 1 < n and stripped[i + 1] in _ASCII_PUNCTUATION:
                i += 2
                continue
            if ch == "]":
                if i + 1 < n and stripped[i + 1] == ":":
                    return True
                in_label = False
                break
            i += 1
    return False


def is_pure_line_addition(before: bytes | None, after: bytes | None) -> bool:
    """Return True iff `after` is a strict inert EOF append onto `before` (D-211, D-213)."""
    if not before or not after:
        return False
    if b"\x00" in before or b"\x00" in after:
        return False
    try:
        before_text = before.decode("utf-8").removeprefix("\ufeff")
        after_text = after.decode("utf-8").removeprefix("\ufeff")
    except UnicodeDecodeError:
        return False

    before_norm = before_text.replace("\r\n", "\n")
    after_norm = after_text.replace("\r\n", "\n")
    if "\r" in before_norm or "\r" in after_norm:
        return False

    before_hidden = Counter(ch for ch in before_norm if _is_hidden_or_format_char(ch))
    after_hidden = Counter(ch for ch in after_norm if _is_hidden_or_format_char(ch))
    if after_hidden - before_hidden:
        return False

    before_breaks = Counter(ch for ch in before_norm if ch in _UNICODE_LINE_BREAKS)
    after_breaks = Counter(ch for ch in after_norm if ch in _UNICODE_LINE_BREAKS)
    if after_breaks - before_breaks:
        return False

    before_lines = _split_lf_lines(before_norm)
    after_lines = _split_lf_lines(after_norm)
    n_before = len(before_lines)
    if not n_before or len(after_lines) <= n_before:
        return False

    if after_lines[:n_before] != before_lines:
        return False

    last_before_nb = -1
    for idx in range(n_before - 1, -1, -1):
        if before_lines[idx].strip(" \t") != "":
            last_before_nb = idx
            break
    if last_before_nb < 0:
        return False

    added_lines = after_lines[n_before:]
    first_added_nb = -1
    for rel_idx, line in enumerate(added_lines):
        if line.strip(" \t") != "":
            first_added_nb = n_before + rel_idx
            break
    if first_added_nb < 0 or (first_added_nb - last_before_nb) < 2:
        return False

    before_starts_fm = before_lines[0].lstrip(" \t").startswith(("---", "+++"))
    after_starts_fm = after_lines[0].lstrip(" \t").startswith(("---", "+++"))
    if after_starts_fm and not before_starts_fm:
        return False

    canon_before = "\n".join(before_lines) + "\n"
    canon_after = "\n".join(after_lines) + "\n"
    b_cc_has, b_cc_fm, b_cc_rest = _cc_frontmatter_split(canon_before)
    a_cc_has, a_cc_fm, a_cc_rest = _cc_frontmatter_split(canon_after)
    if (b_cc_has, b_cc_fm) != (a_cc_has, a_cc_fm) or not a_cc_rest.startswith(b_cc_rest):
        return False
    raw_b_cc = _CC_FRONTMATTER_RE.match(before_norm)
    raw_a_cc = _CC_FRONTMATTER_RE.match(after_norm)
    if bool(raw_b_cc) != bool(raw_a_cc):
        return False
    if raw_b_cc is not None and raw_a_cc is not None and raw_b_cc.group(1) != raw_a_cc.group(1):
        return False

    for line in added_lines:
        if (
            "---" in line
            or "```" in line
            or "~~~" in line
            or "<!--" in line
            or "-->" in line
        ):
            return False
        for ch in line:
            if _is_hidden_or_format_char(ch) or ch in _UNICODE_LINE_BREAKS:
                return False
    if _has_link_ref_opener(added_lines):
        return False

    shared_html_trie: dict[tuple[int, str], int] = {}
    shared_container_trie: dict[tuple[int, str], int] = {}
    (
        before_annotated,
        before_fm,
        before_eof_clean,
        before_stack,
        before_unmatched,
    ) = _annotate_markdown_lines(
        before_lines, shared_html_trie, shared_container_trie,
    )
    if not before_eof_clean:
        return False
    (
        after_annotated,
        after_fm,
        after_eof_clean,
        after_stack,
        after_unmatched,
    ) = _annotate_markdown_lines(
        after_lines, shared_html_trie, shared_container_trie,
    )
    if not after_eof_clean or before_fm != after_fm:
        return False
    if after_annotated[:n_before] != before_annotated:
        return False
    if any(st.startswith("link_ref|") for _, st in after_annotated[n_before:]):
        return False
    if after_unmatched != before_unmatched or after_stack[: len(before_stack)] != before_stack:
        return False
    return True
