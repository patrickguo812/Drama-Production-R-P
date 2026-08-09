import tempfile
import unittest
import zipfile
from pathlib import Path

from drama_studio.docx_reader import chunk_novel, extract_docx


DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>第一章 雨夜</w:t></w:r></w:p>
<w:p><w:r><w:t>林岚收到一条短信。</w:t></w:r></w:p>
<w:p><w:r><w:t>第二章 来电</w:t></w:r></w:p>
<w:p><w:r><w:t>电话再次响起。</w:t></w:r></w:p>
</w:body></w:document>"""


class DocxReaderTests(unittest.TestCase):
    def test_extract_and_detect_chapters(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "novel.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", DOCUMENT)
            novel = extract_docx(path)
            self.assertEqual(novel.title, "novel")
            self.assertEqual(len(novel.chapters), 2)
            self.assertIn("短信", novel.text)
            self.assertGreaterEqual(len(chunk_novel(novel, 20)), 2)

    def test_reject_non_docx(self):
        with self.assertRaises(ValueError):
            extract_docx("novel.txt")


if __name__ == "__main__":
    unittest.main()

