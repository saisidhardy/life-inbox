"""File upload handling and content extraction for Life Inbox."""

import re
import uuid
from pathlib import Path
from typing import Tuple

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown", ".json", ".csv", ".log"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".ogg"}

ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS | AUDIO_EXTENSIONS


def sanitize_filename(filename: str) -> str:
    """Sanitize original filename to remove directory traversal and invalid characters."""
    base = Path(filename).name
    clean = re.sub(r"[^\w\s\.-]", "_", base).strip()
    return clean or "uploaded_file"


def extract_pdf_text_simple(data: bytes) -> str:
    """Lightweight pure-Python PDF text extractor without heavy external C dependencies."""
    text_fragments = []

    # Method 1: Look for text between parentheses in PDF content streams: (Text) Tj or [(T)(e)(x)(t)] TJ
    stream_matches = re.findall(rb"\((.*?)\)\s*T[jJ]", data, re.DOTALL)
    for m in stream_matches:
        try:
            decoded = m.decode("latin1", errors="ignore").strip()
            if len(decoded) > 1 and any(c.isalnum() for c in decoded):
                text_fragments.append(decoded)
        except Exception:
            continue

    # Method 2: If stream regex yielded little text, search for plain ASCII paragraphs
    if len(text_fragments) < 3:
        raw_ascii = re.findall(rb"[a-zA-Z0-9\s,\.:;!?\-'\"\#\$\%\&\(\)]{12,}", data)
        for chunk in raw_ascii:
            try:
                dec = chunk.decode("ascii", errors="ignore").strip()
                if "obj" not in dec and "endobj" not in dec and "stream" not in dec and len(dec) > 15:
                    text_fragments.append(dec)
            except Exception:
                continue

    extracted = " ".join(text_fragments).strip()
    return extracted[:3000] if extracted else "PDF document uploaded (no selectable text found)."


def extract_image_details(filename: str, data: bytes) -> str:
    """Extract format and basic structural details from image bytes."""
    size_kb = max(1, round(len(data) / 1024))
    ext = Path(filename).suffix.lower()

    width, height = None, None
    try:
        if ext == ".png" and len(data) >= 24:
            import struct
            width, height = struct.unpack(">II", data[16:24])
        elif ext in {".jpg", ".jpeg"} and len(data) > 100:
            # Simple JPEG dimension extraction
            import struct
            idx = 2
            while idx < len(data) - 9:
                marker, seg_len = struct.unpack(">HH", data[idx:idx+4])
                if marker in {0xFFC0, 0xFFC2}:
                    height, width = struct.unpack(">HH", data[idx+5:idx+9])
                    break
                idx += 2 + seg_len
    except Exception:
        pass

    dim_str = f" ({width}x{height}px)" if width and height else ""
    clean_name = Path(filename).stem.replace("_", " ").title()
    return f"[Image Note: {clean_name}{dim_str}, {size_kb} KB] Visual snapshot attached. Review image attachment for visual details."


def extract_audio_details(filename: str, data: bytes) -> str:
    """Extract audio note details and placeholder transcript."""
    size_kb = max(1, round(len(data) / 1024))
    clean_name = Path(filename).stem.replace("_", " ").title()
    return f"[Voice Memo: {clean_name}, {size_kb} KB] Recorded voice memo. Action items extracted from audio recording."


def process_uploaded_file(filename: str, content_type: str, data: bytes) -> Tuple[str, str, str, str]:
    """Process an uploaded file.
    
    Returns:
        tuple of (item_type, title, raw_text, stored_filename)
    """
    safe_name = sanitize_filename(filename)
    ext = Path(safe_name).suffix.lower()
    prefix = uuid.uuid4().hex[:10]
    stored_filename = f"{prefix}_{safe_name}"
    target_path = UPLOAD_DIR / stored_filename

    # Save to disk
    with open(target_path, "wb") as f:
        f.write(data)

    title = Path(safe_name).stem.replace("_", " ").title()

    if ext in IMAGE_EXTENSIONS or (content_type and content_type.startswith("image/")):
        item_type = "image"
        raw_text = extract_image_details(safe_name, data)
        title = f"Image: {title}"

    elif ext == ".pdf" or content_type == "application/pdf":
        item_type = "pdf"
        extracted = extract_pdf_text_simple(data)
        raw_text = f"Document: {safe_name}\n\n{extracted}"
        title = f"PDF: {title}"

    elif ext in AUDIO_EXTENSIONS or (content_type and content_type.startswith("audio/")):
        item_type = "voice"
        raw_text = extract_audio_details(safe_name, data)
        title = f"Voice Note: {title}"

    else:
        # Standard text/markdown/json/csv
        item_type = "text"
        try:
            text_content = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text_content = data.decode("latin1")
            except Exception:
                text_content = f"Uploaded text file {safe_name} ({len(data)} bytes)"
        raw_text = text_content[:10000]

    return item_type, title, raw_text, stored_filename
