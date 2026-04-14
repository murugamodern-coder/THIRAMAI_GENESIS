"""
Server-side upload validation: size, declared type, magic bytes, optional ClamAV.

Does not replace WAF; reduces trivial malware / zip bombs on document endpoints.
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import tempfile
from typing import Any

_log = logging.getLogger("thiramai.upload")


def max_upload_bytes() -> int:
    try:
        return max(1024, min(int((os.getenv("THIRAMAI_UPLOAD_MAX_BYTES") or str(10 * 1024 * 1024)).strip()), 50 * 1024 * 1024))
    except ValueError:
        return 10 * 1024 * 1024


def _magic_kind(data: bytes) -> str | None:
    if len(data) >= 5 and data[:5] == b"%PDF-":
        return "pdf"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:1] in (b"{", b"[") or (len(data) >= 5 and data[:5].lower() == b"<?xml"):
        return "textish"
    # CSV / plain text heuristic: printable ratio
    sample = data[:2048]
    if sample and all(32 <= b < 127 or b in (9, 10, 13) for b in sample):
        return "csv_or_text"
    return None


def validate_upload_bytes(
    data: bytes,
    *,
    filename: str,
    content_type: str | None,
    allowed_ext: tuple[str, ...],
    allowed_magic: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """
    Return ``{"ok": True}`` or ``{"ok": False, "error": "..."}``.

    ``allowed_ext`` lowercased suffixes without dot, e.g. ``("pdf","csv")``.
    """
    if not data:
        return {"ok": False, "error": "empty file"}
    lim = max_upload_bytes()
    if len(data) > lim:
        return {"ok": False, "error": f"file too large (max {lim} bytes)"}
    name = (filename or "").lower().strip()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in allowed_ext:
        return {"ok": False, "error": f"extension .{ext} not allowed ({', '.join(allowed_ext)})"}
    ct = (content_type or "").lower()
    if ct and "application/octet-stream" not in ct:
        if ext == "pdf" and "pdf" not in ct:
            pass  # browsers vary; magic is authoritative below
        if ext in ("csv", "txt") and "csv" not in ct and "text" not in ct and "spreadsheet" not in ct:
            pass
    magic = _magic_kind(data[:4096])
    if allowed_magic:
        if magic not in allowed_magic:
            return {"ok": False, "error": "content does not match expected file type"}
    elif ext == "pdf" and magic != "pdf":
        return {"ok": False, "error": "not a valid PDF payload"}
    elif ext in ("png", "jpg", "jpeg") and magic not in ("png", "jpeg"):
        return {"ok": False, "error": "not a valid image payload"}
    elif ext == "csv" and magic not in ("csv_or_text", "textish"):
        return {"ok": False, "error": "not a valid CSV/text payload"}

    clam = (os.getenv("THIRAMAI_CLAMAV_HOST") or "").strip()
    if clam:
        err = _clamav_scan_bytes(data)
        if err:
            return {"ok": False, "error": err}
    return {"ok": True, "magic": magic}


def _clamav_scan_bytes(data: bytes) -> str | None:
    """INSTREAM scan via clamd TCP (port 3310). Returns error string or None if clean / unavailable."""
    host = (os.getenv("THIRAMAI_CLAMAV_HOST") or "").strip()
    if not host:
        return None
    try:
        port = int((os.getenv("THIRAMAI_CLAMAV_PORT") or "3310").strip())
    except ValueError:
        port = 3310
    try:
        with socket.create_connection((host, port), timeout=5.0) as sock:
            sock.sendall(b"zINSTREAM\0")
            chunk_size = 2048
            offset = 0
            while offset < len(data):
                piece = data[offset : offset + chunk_size]
                sock.sendall(struct.pack("!I", len(piece)) + piece)
                offset += len(piece)
            sock.sendall(struct.pack("!I", 0))
            resp = b""
            while True:
                part = sock.recv(4096)
                if not part:
                    break
                resp += part
                if b"\n" in resp:
                    break
        text = resp.decode("utf-8", errors="replace").strip()
        if "OK" in text and "FOUND" not in text:
            return None
        if "FOUND" in text:
            return "virus scan flagged content"
        return None
    except Exception as exc:
        _log.warning("clamav scan skipped: %s", exc)
        return None


def validate_upload_file_sync(
    data: bytes,
    *,
    filename: str,
    content_type: str | None,
    allowed_ext: tuple[str, ...],
    allowed_magic: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Same as ``validate_upload_bytes``; name kept for call-site clarity."""
    return validate_upload_bytes(data, filename=filename, content_type=content_type, allowed_ext=allowed_ext, allowed_magic=allowed_magic)
