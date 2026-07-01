"""Chunking pipeline for EcoDB ingestion — Task 4.4."""
import logging
import re
from dataclasses import dataclass, field

import tiktoken

log = logging.getLogger("ecodb.chunker")

CHUNK_SIZE = 960
CHUNK_OVERLAP = 128
AUDIO_WINDOW_SEC = 60
AUDIO_OVERLAP_SEC = 10

_enc = tiktoken.get_encoding("cl100k_base")


@dataclass
class ChunkResult:
    content: str
    chunk_index: int
    section_path: str | None = None
    metadata: dict = field(default_factory=dict)


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _split_with_overlap(text: str, max_tokens: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into chunks of max_tokens with overlap tokens carried from previous chunk."""
    tokens = _enc.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(_enc.decode(chunk_tokens))
        if end >= len(tokens):
            break
        start = end - overlap
    return chunks


def chunk_document(parse_result, doc_type: str) -> list[ChunkResult]:
    from parsers import TranscriptionResult
    if isinstance(parse_result, TranscriptionResult):
        return _chunk_audio(parse_result)
    if doc_type in ("md", "markdown"):
        return _chunk_markdown(parse_result.text)
    elif doc_type in ("pdf", "docx", "html"):
        return _chunk_docling(parse_result)
    else:
        return _chunk_txt(parse_result.text)


# ---------------------------------------------------------------------------
# Header-aware markdown chunking
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)


def _build_section_path(stack: list[tuple[int, str]]) -> str:
    parts = []
    for i, (_, title) in enumerate(stack):
        parts.append(f"§ {title}" if i == 0 else title)
    return " > ".join(parts)


def _chunk_markdown(text: str) -> list[ChunkResult]:
    header_matches = list(_HEADER_RE.finditer(text))
    if not header_matches:
        return _chunk_txt(text)

    chunks: list[ChunkResult] = []
    idx = 0

    # Capture preamble (text before first header) as section_path=None chunk
    preamble = text[:header_matches[0].start()].strip()
    if preamble:
        if _count_tokens(preamble) <= CHUNK_SIZE:
            chunks.append(ChunkResult(content=preamble, chunk_index=idx, section_path=None))
            idx += 1
        else:
            for sc in _merge_into_chunks([p.strip() for p in preamble.split("\n\n") if p.strip()], None):
                sc.chunk_index = idx
                idx += 1
                chunks.append(sc)

    sections = []
    for i, m in enumerate(header_matches):
        end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(text)
        sections.append((len(m.group(1)), m.group(2).strip(), text[m.start():end].strip()))

    stack: list[tuple[int, str]] = []

    for level, title, content in sections:
        stack = [(l, t) for l, t in stack if l < level]
        stack.append((level, title))
        section_path = _build_section_path(stack)

        if _count_tokens(content) <= CHUNK_SIZE:
            chunks.append(ChunkResult(content=content, chunk_index=idx, section_path=section_path))
            idx += 1
        else:
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            for sc in _merge_into_chunks(paragraphs, section_path):
                sc.chunk_index = idx
                idx += 1
                chunks.append(sc)

    return chunks


# ---------------------------------------------------------------------------
# Docling output (pdf / docx / html — Docling exports to markdown)
# ---------------------------------------------------------------------------

def _chunk_docling(parse_result) -> list[ChunkResult]:
    chunks = _chunk_markdown(parse_result.text)
    idx = len(chunks)
    for table_md in getattr(parse_result, "tables", []):
        if _count_tokens(table_md) <= CHUNK_SIZE:
            chunks.append(ChunkResult(
                content=table_md, chunk_index=idx,
                section_path=None, metadata={"is_table": True},
            ))
            idx += 1
        else:
            for sub in _split_with_overlap(table_md):
                chunks.append(ChunkResult(
                    content=sub, chunk_index=idx,
                    section_path=None, metadata={"is_table": True},
                ))
                idx += 1
    return chunks


# ---------------------------------------------------------------------------
# Plain text — recursive split: paragraphs → sentences → hard split
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


def _chunk_txt(text: str) -> list[ChunkResult]:
    log.warning("No document structure detected, using fallback recursive split.")
    parts: list[str] = []
    for para in (p.strip() for p in text.split("\n\n") if p.strip()):
        if _count_tokens(para) <= CHUNK_SIZE:
            parts.append(para)
        else:
            for sent in (s.strip() for s in _SENTENCE_RE.split(para) if s.strip()):
                if _count_tokens(sent) <= CHUNK_SIZE:
                    parts.append(sent)
                else:
                    parts.extend(_split_with_overlap(sent))

    merged = _merge_into_chunks(parts, section_path=None)
    for i, chunk in enumerate(merged):
        chunk.chunk_index = i
    return merged


# ---------------------------------------------------------------------------
# Audio — group Whisper segments into ~60s windows with 10s overlap
# ---------------------------------------------------------------------------

def _chunk_audio(result) -> list[ChunkResult]:
    segments = result.segments
    if not segments:
        return []

    chunks: list[ChunkResult] = []
    chunk_index = 0
    window_start = segments[0]["start"]

    while True:
        window_end = window_start + AUDIO_WINDOW_SEC
        window_segs = [s for s in segments if window_start <= s["start"] < window_end]

        if not window_segs:
            window_start += AUDIO_WINDOW_SEC
            continue

        chunks.append(ChunkResult(
            content=" ".join(s["text"] for s in window_segs).strip(),
            chunk_index=chunk_index,
            section_path=None,
            metadata={
                "timestamp_start": window_segs[0]["start"],
                "timestamp_end": window_segs[-1]["end"],
            },
        ))
        chunk_index += 1

        if all(s["start"] < window_end for s in segments):
            break
        window_start = window_end - AUDIO_OVERLAP_SEC

    return chunks


# ---------------------------------------------------------------------------
# Shared: merge parts into token-capped chunks with paragraph-level overlap
# ---------------------------------------------------------------------------

def _merge_into_chunks(parts: list[str], section_path: str | None) -> list[ChunkResult]:
    chunks: list[ChunkResult] = []
    current: list[str] = []
    current_tokens = 0

    def _flush():
        if current:
            chunks.append(ChunkResult(
                content="\n\n".join(current),
                chunk_index=0,
                section_path=section_path,
            ))

    for part in parts:
        pt = _count_tokens(part)
        if pt > CHUNK_SIZE:
            _flush()
            current, current_tokens = [], 0
            for sub in _split_with_overlap(part):
                chunks.append(ChunkResult(content=sub, chunk_index=0, section_path=section_path))
        elif current_tokens + pt > CHUNK_SIZE:
            _flush()
            # Carry overlap: last parts fitting within CHUNK_OVERLAP tokens
            overlap: list[str] = []
            overlap_tokens = 0
            for p in reversed(current):
                ptt = _count_tokens(p)
                if overlap_tokens + ptt <= CHUNK_OVERLAP:
                    overlap.insert(0, p)
                    overlap_tokens += ptt
                else:
                    break
            current = overlap + [part]
            current_tokens = overlap_tokens + pt
        else:
            current.append(part)
            current_tokens += pt

    _flush()
    return chunks
