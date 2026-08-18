from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class ExtractedNovel:
    title: str
    paragraphs: list[str]
    chapters: list[tuple[str, str]]

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


def extract_docx(path: str | Path) -> ExtractedNovel:
    source = Path(path)
    if source.suffix.lower() != ".docx":
        raise ValueError("Please choose a .docx Word document.")
    try:
        with zipfile.ZipFile(source) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError("This file is not a readable Word .docx document.") from exc

    paragraphs: list[str] = []
    for p in root.iter(W + "p"):
        parts: list[str] = []
        for node in p.iter():
            if node.tag == W + "t" and node.text:
                parts.append(node.text)
            elif node.tag == W + "tab":
                parts.append("\t")
            elif node.tag == W + "br":
                parts.append("\n")
        text = re.sub(r"[ \t]+", " ", "".join(parts)).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        raise ValueError("No readable text was found in the document.")
    return ExtractedNovel(source.stem, paragraphs, _detect_chapters(paragraphs))


def _detect_chapters(paragraphs: list[str]) -> list[tuple[str, str]]:
    heading = re.compile(r"^(第[一二三四五六七八九十百千万\d]+[章节回卷]|chapter\s+\d+|序章|楔子|尾声)", re.I)
    groups: list[tuple[str, list[str]]] = []
    current_title = "正文"
    current: list[str] = []
    for p in paragraphs:
        if len(p) <= 80 and heading.search(p):
            if current:
                groups.append((current_title, current))
            current_title, current = p, []
        else:
            current.append(p)
    if current:
        groups.append((current_title, current))
    return [(title, "\n".join(body)) for title, body in groups] or [("正文", "\n".join(paragraphs))]


def chunk_novel(novel: ExtractedNovel, max_chars: int = 24000) -> list[str]:
    chunks: list[str] = []
    current = ""
    for title, body in novel.chapters:
        section = f"\n## {title}\n{body}"
        while len(section) > max_chars:
            room = max_chars - len(current)
            if room > 1000:
                current += section[:room]
                section = section[room:]
            chunks.append(current.strip())
            current = ""
        if current and len(current) + len(section) > max_chars:
            chunks.append(current.strip())
            current = ""
        current += section
    if current.strip():
        chunks.append(current.strip())
    return chunks

