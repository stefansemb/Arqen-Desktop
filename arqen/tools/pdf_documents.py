from pathlib import Path
from typing import Any

from arqen.tools.base import Tool


class ReadPdfTool(Tool):
    name = "read_pdf"
    description = "Extracts text from a PDF file inside the Arqen workspace."
    requires_confirmation = False
    arguments_schema = {"path": str}

    def run(self, arguments: dict[str, Any]) -> str:
        root = Path.cwd().resolve()
        candidate = (root / arguments["path"]).resolve()
        if root not in candidate.parents or candidate.suffix.lower() != ".pdf":
            raise PermissionError("PDF path must be inside the Arqen workspace")
        if not candidate.is_file():
            raise FileNotFoundError(f"File not found: {arguments['path']}")
        if candidate.stat().st_size > 25_000_000:
            raise ValueError("PDF is larger than the 25 MB read limit")
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF reading requires the pypdf package") from exc

        reader = PdfReader(str(candidate))
        pages = []
        for index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"--- Page {index + 1} ---\n{text.strip()}")
        return "\n\n".join(pages) or "No text layer found. This PDF may be scanned."

