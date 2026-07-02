"""Document parsers for EcoDB ingestion pipeline — Tasks 4.2 + 4.3."""
import asyncio
import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger("ecodb.parsers")

MAX_AUDIO_DURATION_SEC = int(os.environ.get("MAX_AUDIO_DURATION_SEC", "3600"))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
MAX_DOC_SIZE_BYTES = int(os.environ.get("MAX_DOC_SIZE_BYTES", str(50 * 1024 * 1024)))  # 50MB
_WHISPER_MODEL_ALLOWLIST = {"tiny", "base", "small", "medium", "large", "large-v2", "large-v3"}

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # Force CPU for all parsers

_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        if WHISPER_MODEL not in _WHISPER_MODEL_ALLOWLIST:
            raise ValueError(f"WHISPER_MODEL '{WHISPER_MODEL}' not in allowlist: {_WHISPER_MODEL_ALLOWLIST}")
        try:
            import whisper
        except Exception as _imp_err:
            raise RuntimeError(
                f"whisper import failed (likely numba conflict): {_imp_err}. "
                "Try: pip install numba>=0.59 or run with --no-cov"
            ) from _imp_err
        _whisper_model = whisper.load_model(WHISPER_MODEL, device="cpu")
    return _whisper_model


@dataclass
class ParseResult:
    text: str
    sections: list[dict] = field(default_factory=list)  # [{title, level, content}]
    tables: list[str] = field(default_factory=list)      # markdown tables
    metadata: dict = field(default_factory=dict)          # {title, author, pages, language, size_bytes}


@dataclass
class TranscriptionResult:
    text: str
    segments: list[dict] = field(default_factory=list)   # [{text, start, end}]
    language: str = ""
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Task 4.2 — Docling parser (PDF, TXT, MD, DOCX, HTML)
# ---------------------------------------------------------------------------

async def parse_document(file_path: str, doc_type: str) -> ParseResult:
    """Parse document using Docling. CPU-only (CUDA_VISIBLE_DEVICES='').

    Supported: pdf, txt, md, docx, html
    Returns ParseResult with extracted text + structure.
    """
    real = os.path.realpath(file_path)
    if not os.path.isfile(real):
        raise FileNotFoundError(f"File not found: {file_path}")
    size_bytes = os.path.getsize(real)
    if size_bytes > MAX_DOC_SIZE_BYTES:
        raise ValueError(f"File too large: {size_bytes} bytes (max {MAX_DOC_SIZE_BYTES})")

    if doc_type in ("txt", "md"):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        sections = _extract_markdown_sections(text) if doc_type == "md" else []
        return ParseResult(
            text=text,
            sections=sections,
            metadata={"size_bytes": size_bytes, "doc_type": doc_type},
        )

    # PDF, DOCX, HTML — use Docling
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        raise RuntimeError("docling not installed. Add to requirements.txt and rebuild.")

    loop = asyncio.get_running_loop()

    def _convert() -> ParseResult:
        converter = DocumentConverter()
        result = converter.convert(file_path)
        doc = result.document

        text = doc.export_to_markdown()

        sections = []
        for item in doc.iterate_items():
            if hasattr(item, "label") and "heading" in str(item.label).lower():
                sections.append({
                    "title": item.text if hasattr(item, "text") else str(item),
                    "level": getattr(item, "level", 1),
                    "content": "",
                })

        tables = []
        for table in (doc.tables if hasattr(doc, "tables") else []):
            try:
                tables.append(table.export_to_markdown())
            except Exception:
                pass

        metadata = {
            "size_bytes": size_bytes,
            "doc_type": doc_type,
            "title": getattr(doc, "title", None),
            "pages": getattr(doc, "num_pages", None),
        }

        log.info(
            "Parsed %s (%s): %d chars, %d sections, %d tables",
            file_path, doc_type, len(text), len(sections), len(tables),
        )
        return ParseResult(text=text, sections=sections, tables=tables, metadata=metadata)

    return await loop.run_in_executor(None, _convert)


def _extract_markdown_sections(text: str) -> list[dict]:
    sections = []
    for match in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE):
        sections.append({
            "title": match.group(2).strip(),
            "level": len(match.group(1)),
            "content": "",
        })
    return sections


# ---------------------------------------------------------------------------
# Task 4.3 — Whisper parser (audio transcription)
# ---------------------------------------------------------------------------

async def transcribe_audio(file_path: str) -> TranscriptionResult:
    """Transcribe audio using Whisper CPU. Auto-detects language.

    MAX_AUDIO_DURATION_SEC enforced (default 3600s = 1h).
    Model configurable via WHISPER_MODEL env var.
    """
    real = os.path.realpath(file_path)
    if not os.path.isfile(real):
        raise FileNotFoundError(f"File not found: {file_path}")
    size_bytes = os.path.getsize(real)
    if size_bytes > MAX_DOC_SIZE_BYTES:
        raise ValueError(f"Audio too large: {size_bytes} bytes (max {MAX_DOC_SIZE_BYTES})")

    duration: float | None = None

    # Check duration before loading model (async — does not block event loop)
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            duration = float(stdout.decode().strip())
            if duration > MAX_AUDIO_DURATION_SEC:
                raise ValueError(
                    f"Audio duration {duration:.0f}s exceeds MAX_AUDIO_DURATION_SEC={MAX_AUDIO_DURATION_SEC}"
                )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(
                f"ffprobe timed out for {Path(file_path).name} — rejecting audio (fail-closed)"
            )
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found — cannot validate audio duration. Install ffmpeg.")
    except ValueError:
        raise

    try:
        import whisper  # noqa: F401 — guard only; model loaded via _get_whisper_model
    except ImportError:
        raise RuntimeError("openai-whisper not installed. Add to requirements.txt and rebuild.")
    except Exception as _imp_err:
        raise RuntimeError(
            f"whisper import failed (likely numba conflict): {_imp_err}. "
            "Try: pip install numba>=0.59 or run with --no-cov"
        ) from _imp_err

    loop = asyncio.get_running_loop()

    def _transcribe() -> dict:
        return _get_whisper_model().transcribe(file_path)

    result = await loop.run_in_executor(None, _transcribe)

    segments = [
        {"text": seg["text"].strip(), "start": seg["start"], "end": seg["end"]}
        for seg in result.get("segments", [])
    ]
    language = result.get("language", "unknown")
    full_text = result.get("text", "").strip()

    log.info(
        "Transcribed %s: %d chars, %d segments, language=%s",
        file_path, len(full_text), len(segments), language,
    )

    return TranscriptionResult(
        text=full_text,
        segments=segments,
        language=language,
        metadata={"whisper_model": WHISPER_MODEL, "duration_sec": duration},
    )
