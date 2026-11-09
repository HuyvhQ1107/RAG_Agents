"""Document parser for PDF (text-layer), DOCX, HTML, and Markdown with magic-byte validation (T051, R7)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from pypdf import PdfReader

from app.db.models.document import DocumentLanguage


class DocumentParseError(Exception):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass
class ParsedBlock:
    kind: str  # "heading" | "paragraph" | "table"
    text: str
    heading_level: int = 0
    page: int | None = 1


@dataclass
class ParsedDocument:
    blocks: list[ParsedBlock] = field(default_factory=list)
    page_count: int | None = None
    language: DocumentLanguage = DocumentLanguage.vi


def detect_mime_type(filename: str, data: bytes) -> str:
    """Validate file format using magic bytes and filename extension."""
    fname = filename.lower()
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    # DOCX is a ZIP archive starting with PK\x03\x04 (or encrypted OLE2 \xd0\xcf\x11\xe0)
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise DocumentParseError(
            "encrypted_unsupported",
            "File Office được đặt mật khẩu hoặc mã hóa không được hỗ trợ.",
        )
    if data.startswith(b"PK\x03\x04") and fname.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if fname.endswith((".html", ".htm")) or b"<html" in data[:512].lower():
        return "text/html"
    if fname.endswith((".md", ".markdown")):
        return "text/markdown"
    raise DocumentParseError(
        "unsupported_format",
        f"Định dạng file '{filename}' không được hỗ trợ (chỉ hỗ trợ PDF, DOCX, HTML, Markdown).",
    )


def _detect_language(text: str) -> DocumentLanguage:
    vi_chars = len(
        re.findall(
            r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]",
            text.lower(),
        )
    )
    en_words = len(re.findall(r"\b(?:the|and|for|with|policy|employee|company|leave)\b", text.lower()))
    if vi_chars > 5 and en_words > 10:
        return DocumentLanguage.mixed
    if vi_chars > 2:
        return DocumentLanguage.vi
    return DocumentLanguage.en


def _parse_lines_into_blocks(text: str, page: int | None = 1) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        raw = lines[idx].strip()
        if not raw:
            idx += 1
            continue

        # Markdown / numbered / Vietnamese section headings ("# ...", "Chương 1...", "Điều 5...", "Mục 2...")
        md_heading = re.match(r"^(#{1,6})\s+(.+)$", raw)
        if md_heading:
            blocks.append(
                ParsedBlock(
                    kind="heading",
                    text=md_heading.group(2).strip(),
                    heading_level=len(md_heading.group(1)),
                    page=page,
                )
            )
            idx += 1
            continue

        vn_heading = re.match(
            r"^(?:(Chương|Phần|Chapter|Part)\s+\w+|(Mục|Section)\s+\w+|(Điều|Article)\s+\d+)[:.\s\-]*(.*)$",
            raw,
            flags=re.I,
        )
        if vn_heading and len(raw) <= 140:
            level = 1 if vn_heading.group(1) else (2 if vn_heading.group(2) else 3)
            blocks.append(
                ParsedBlock(
                    kind="heading",
                    text=raw,
                    heading_level=level,
                    page=page,
                )
            )
            idx += 1
            continue

        # Markdown pipe table detection
        if raw.startswith("|") and raw.endswith("|"):
            table_lines = [raw]
            idx += 1
            while idx < len(lines) and lines[idx].strip().startswith("|"):
                table_lines.append(lines[idx].strip())
                idx += 1
            blocks.append(
                ParsedBlock(
                    kind="table",
                    text="\n".join(table_lines),
                    page=page,
                )
            )
            continue

        # Regular paragraph
        para_lines = [raw]
        idx += 1
        while idx < len(lines):
            nxt = lines[idx].strip()
            if (
                not nxt
                or nxt.startswith("#")
                or (nxt.startswith("|") and nxt.endswith("|"))
                or re.match(r"^(?:Chương|Phần|Mục|Điều|Chapter|Section|Article)\s+\w+", nxt, re.I)
            ):
                break
            para_lines.append(nxt)
            idx += 1
        blocks.append(
            ParsedBlock(
                kind="paragraph",
                text=" ".join(para_lines),
                page=page,
            )
        )
    return blocks


def parse_document_bytes(filename: str, data: bytes, max_bytes: int = 52_428_800) -> tuple[str, ParsedDocument]:
    if len(data) > max_bytes:
        raise DocumentParseError("too_large", "Dung lượng file vượt quá giới hạn 50 MB.")
    if not data:
        raise DocumentParseError("empty_document", "File rỗng.")

    mime_type = detect_mime_type(filename, data)

    if mime_type == "application/pdf":
        # Check for PDF encryption markers or parse via pypdf
        if b"/Encrypt" in data:
            raise DocumentParseError(
                "encrypted_unsupported",
                "File PDF được đặt mật khẩu không được hỗ trợ.",
            )
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise DocumentParseError(
                    "encrypted_unsupported",
                    "File PDF được đặt mật khẩu không được hỗ trợ.",
                )
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError("parse_error", f"Không thể đọc cấu trúc PDF: {exc}") from exc

        page_count = len(reader.pages)
        if page_count == 0:
            raise DocumentParseError("empty_document", "File PDF không có trang nào.")

        blocks: list[ParsedBlock] = []
        total_chars = 0
        for page_num, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            total_chars += len(re.sub(r"\s+", "", page_text))
            if page_text:
                blocks.extend(_parse_lines_into_blocks(page_text, page=page_num))

        # Detect scanned image PDF (low character density across pages, OCR disabled per R7)
        if total_chars < max(20, page_count * 15):
            raise DocumentParseError(
                "scanned_pdf_unsupported",
                "File PDF dạng ảnh scan (không có lớp văn bản) không được hỗ trợ ở phiên bản đầu.",
            )
        full_text = "\n".join(b.text for b in blocks)
        return mime_type, ParsedDocument(
            blocks=blocks,
            page_count=page_count,
            language=_detect_language(full_text),
        )

    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        import docx

        try:
            doc = docx.Document(io.BytesIO(data))
        except Exception as exc:
            if "encrypted" in str(exc).lower() or "password" in str(exc).lower():
                raise DocumentParseError(
                    "encrypted_unsupported",
                    "File Word được đặt mật khẩu không được hỗ trợ.",
                ) from exc
            raise DocumentParseError("parse_error", f"Không thể đọc file Word: {exc}") from exc

        blocks = []
        for para in doc.paragraphs:
            txt = para.text.strip()
            if not txt:
                continue
            style_name = (para.style.name if para.style else "").lower()
            if style_name.startswith("heading"):
                lvl_match = re.search(r"(\d+)", style_name)
                lvl = int(lvl_match.group(1)) if lvl_match else 1
                blocks.append(ParsedBlock(kind="heading", text=txt, heading_level=lvl, page=1))
            else:
                blocks.extend(_parse_lines_into_blocks(txt, page=1))

        for table in doc.tables:
            md_rows: list[str] = []
            for r_idx, row in enumerate(table.rows):
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                md_rows.append("| " + " | ".join(cells) + " |")
                if r_idx == 0:
                    md_rows.append("| " + " | ".join("---" for _ in cells) + " |")
            if md_rows:
                blocks.append(ParsedBlock(kind="table", text="\n".join(md_rows), page=1))

        if not blocks:
            raise DocumentParseError("empty_document", "File Word không có nội dung văn bản.")
        full_text = "\n".join(b.text for b in blocks)
        return mime_type, ParsedDocument(
            blocks=blocks,
            page_count=1,
            language=_detect_language(full_text),
        )

    if mime_type == "text/html":
        text_content = data.decode("utf-8", errors="replace")
        soup = BeautifulSoup(text_content, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        blocks = []
        for elem in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            name = (elem.name or "").lower()
            if name in ("h1", "h2", "h3", "h4"):
                txt = elem.get_text(" ", strip=True)
                if txt:
                    blocks.append(
                        ParsedBlock(
                            kind="heading",
                            text=txt,
                            heading_level=int(name[1]),
                            page=None,
                        )
                    )
            elif name == "table":
                rows_md: list[str] = []
                for r_idx, tr in enumerate(elem.find_all("tr")):
                    cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
                    if cells:
                        rows_md.append("| " + " | ".join(cells) + " |")
                        if r_idx == 0:
                            rows_md.append("| " + " | ".join("---" for _ in cells) + " |")
                if rows_md:
                    blocks.append(ParsedBlock(kind="table", text="\n".join(rows_md), page=None))
            else:
                txt = elem.get_text(" ", strip=True)
                if txt:
                    blocks.append(ParsedBlock(kind="paragraph", text=txt, page=None))

        if not blocks:
            plain = soup.get_text("\n", strip=True)
            blocks = _parse_lines_into_blocks(plain, page=None)
        if not blocks:
            raise DocumentParseError("empty_document", "File HTML không có nội dung văn bản.")
        full_text = "\n".join(b.text for b in blocks)
        return mime_type, ParsedDocument(
            blocks=blocks,
            page_count=None,
            language=_detect_language(full_text),
        )

    # Markdown
    md_text = data.decode("utf-8", errors="replace").strip()
    if not md_text:
        raise DocumentParseError("empty_document", "File Markdown rỗng.")
    blocks = _parse_lines_into_blocks(md_text, page=None)
    if not blocks:
        raise DocumentParseError("empty_document", "File Markdown không có nội dung.")
    return mime_type, ParsedDocument(
        blocks=blocks,
        page_count=None,
        language=_detect_language(md_text),
    )
