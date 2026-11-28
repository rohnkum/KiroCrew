"""Outbound rendering for the Weixin channel.

iLink clients render Markdown natively, so we PRESERVE Markdown (headers,
tables, fenced code) and only split when a payload exceeds the 4000-char limit,
through the shared fence-aware splitter in ``messaging/split.py``.

Ported from Nous Research's Hermes Agent ``gateway/platforms/weixin.py``
(MIT License): ``_normalize_markdown_blocks`` + ``_split_markdown_blocks``.
"""

from __future__ import annotations

from kiro_crew.messaging.renderer import chunk_for_transport
from kiro_crew.messaging.split import (
    FENCE_BODY,
    FENCE_CLOSE,
    FENCE_OPEN,
    FENCE_OUTSIDE,
    iter_fence_lines,
)
from kiro_crew.messaging.transport import TransportCapabilities
from kiro_crew.security import redact_credentials, redact_exfiltration_urls

WEIXIN_CHUNK_LIMIT = 4000


def _fence_lines(content: str) -> list[tuple[str, str]]:
    """``(line, role)`` per line, read with the shared fence reader.

    The reader knows backtick and tilde fences of any length and closes one only
    with a run of the same character at least as long. It reads each line without
    its leading whitespace, so a fence indented under a list item still counts, as
    it always has here; every line comes back as written.
    """
    lines = (content or "").splitlines()
    read = iter_fence_lines("\n".join(line.lstrip() for line in lines))
    return [(line, role) for line, (_bare, role) in zip(lines, read)]


def normalize_markdown(content: str) -> str:
    """Collapse >1 consecutive blank line (outside code fences); trim ends."""
    result: list[str] = []
    blank_run = 0
    for raw, role in _fence_lines(content):
        line = raw.rstrip()
        if role != FENCE_OUTSIDE:
            result.append(line)
            blank_run = 0
            continue
        if not line.strip():
            blank_run += 1
            if blank_run <= 1:
                result.append("")
            continue
        blank_run = 0
        result.append(line)
    return "\n".join(result).strip()


def split_markdown_blocks(content: str) -> list[str]:
    """Split into logical blocks (paragraphs + intact fenced code blocks)."""
    if not content:
        return []
    blocks: list[str] = []
    current: list[str] = []
    for raw, role in _fence_lines(content):
        line = raw.rstrip()
        if role in (FENCE_OPEN, FENCE_CLOSE):
            if role == FENCE_OPEN and current:
                blocks.append("\n".join(current).strip())
                current = []
            current.append(line)
            if role == FENCE_CLOSE:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        if role == FENCE_BODY:
            current.append(line)
            continue
        if not line.strip():
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def render_chunks(content: str, limit: int = WEIXIN_CHUNK_LIMIT) -> list[str]:
    """Return delivery-ready message chunks.

    Whole content stays one message when it fits. Otherwise the character path
    of ``chunk_for_transport`` cuts it with the shared fence-aware splitter: a
    fence spanning a cut is sealed in one chunk and reopened, info string
    included, in the next, a line is cut only when it cannot fit a chunk at all,
    and each chunk is bounded to ``limit`` before it ships.
    """
    content = normalize_markdown(content)
    if not content:
        return []
    if len(content) <= limit:
        return [content]
    caps = TransportCapabilities(max_message_chars=limit)
    return chunk_for_transport(content, caps, redactor=_redact_all)


def _redact_all(text: str) -> str:
    """Both outbound redactors as one callable, for the splitter's seam grade."""
    out, _ = redact_exfiltration_urls(text)
    out, _ = redact_credentials(out)
    return out
