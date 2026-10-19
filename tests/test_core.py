import base64
import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from lxml import etree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from core import prepare_epub, H, OP, EP, NS, resolve

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aY1sAAAAASUVORK5CYII=")


def document(body):
    return ('<html xmlns="' + H + '" xmlns:epub="' + EP + '"><head><title>Test</title></head><body>' + body + '</body></html>').encode()


def book(path, shared=False, external=False, missing_fragment=False, no_cover=False):
    ref = "../Notes/end.xhtml#n1" if external else "#n1"
    marker = '<a epub:type="noteref" id="r1" href="' + ref + '">[1]</a>'
    body = '<h3>Chapter 1</h3><p>First paragraph ' + marker + '.</p>'
    if shared:
        body += '<p>Second paragraph <a epub:type="noteref" id="r2" href="' + ref + '">[1]</a>.</p>'
    note = '<aside epub:type="footnote" id="n1"><p>Translator explanation <a href="../Text/ch1.xhtml#r1" role="doc-backlink">return</a>.</p>'
    if external:
        note += '<p><img src="stamp.png" alt="stamp"/></p>'
    note += '</aside>'
    if not external:
        body += note
    data = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        "OEBPS/Text/ch1.xhtml": document(body),
        "OEBPS/Text/ch2.xhtml": document('<h3>Chapter 2</h3><p>Ordinary content.</p>'),
        "OEBPS/Text/toc.xhtml": document('<nav epub:type="toc" id="toc"><a href="ch1.xhtml">Chapter 1</a><a href="ch2.xhtml">Chapter 2</a></nav>'),
        "OEBPS/toc.ncx": ('<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap><navPoint><navLabel><text>Chapter 1</text></navLabel><content src="Text/ch1.xhtml"/></navPoint><navPoint><navLabel><text>' + ("Unrelated chapter" if missing_fragment else "Chapter 2") + '</text></navLabel><content src="Text/ch2.xhtml' + ("#does-not-exist" if missing_fragment else "") + '"/></navPoint></navMap></ncx>').encode(),
    }
    manifest = '<item id="ch1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/><item id="ch2" href="Text/ch2.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="Text/toc.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    if external:
        data["OEBPS/Notes/end.xhtml"] = document(note)
        data["OEBPS/Notes/stamp.png"] = PNG
        manifest += '<item id="notes" href="Notes/end.xhtml" media-type="application/xhtml+xml"/><item id="stamp" href="Notes/stamp.png" media-type="image/png"/>'
    guide = ""
    if not no_cover:
        data["OEBPS/Text/cover.xhtml"] = document('<img src="../Images/cover.png" alt="Cover"/>')
        data["OEBPS/Images/cover.png"] = PNG
        manifest += '<item id="cover-page" href="Text/cover.xhtml" media-type="application/xhtml+xml"/><item id="cover-image" href="Images/cover.png" media-type="image/png"/>'
        guide = '<guide><reference type="cover" href="Text/cover.xhtml"/></guide>'
    data["OEBPS/content.opf"] = ('<package xmlns="' + OP + '" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0" unique-identifier="uid"><metadata><dc:title>Test</dc:title><dc:identifier id="uid">unchanged-book-identity</dc:identifier></metadata><manifest>' + manifest + '</manifest><spine toc="ncx"><itemref idref="ch1"/><itemref idref="ch2"/></spine>' + guide + '</package>').encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in data.items():
            z.writestr(name, content)
    return data


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.output = self.root / "input.epub", self.root / "output.epub"

    def tearDown(self):
        self.temp.cleanup()

    def test_inline_note_is_a_visible_paragraph_and_source_is_unchanged(self):
        original = book(self.source)
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        report = prepare_epub(self.source, self.output)
        self.assertEqual(report["inline_notes"], 1)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), digest)
        with zipfile.ZipFile(self.output) as z:
            tree = E.fromstring(z.read("OEBPS/Text/ch1.xhtml"))
            note = tree.xpath('.//h:div[@class="kap-note"]', namespaces=NS)[0]
            self.assertEqual(E.QName(note.getprevious()).localname, "p")
            self.assertIn("Translator explanation", "".join(note.itertext()))
            self.assertFalse(tree.xpath('.//h:aside|.//*[@epub:type="noteref"]', namespaces=NS))
            self.assertEqual(z.read("OEBPS/Images/cover.png"), original["OEBPS/Images/cover.png"])
            self.assertEqual(z.infolist()[0].filename, "mimetype")
            self.assertEqual(z.infolist()[0].compress_type, zipfile.ZIP_STORED)
            self.assertIsNone(z.testzip())

    def test_repeated_processing_does_not_duplicate_anything(self):
        book(self.source)
        prepare_epub(self.source, self.output)
        second = self.root / "second.epub"
        report = prepare_epub(self.output, second)
        self.assertFalse(report["changed"])
        self.assertFalse(second.exists())

    def test_cross_file_note_images_keep_correct_paths(self):
        book(self.source, external=True)
        report = prepare_epub(self.source, self.output)
        self.assertEqual(report["inline_notes"], 1)
        with zipfile.ZipFile(self.output) as z:
            tree = E.fromstring(z.read("OEBPS/Text/ch1.xhtml"))
            source = tree.xpath('.//h:div[@class="kap-note"]//h:img/@src', namespaces=NS)[0]
            self.assertEqual(resolve("OEBPS/Text/ch1.xhtml", source)[0], "OEBPS/Notes/stamp.png")
            self.assertIn("OEBPS/Notes/stamp.png", z.namelist())

    def test_shared_notes_are_preserved(self):
        book(self.source, shared=True)
        report = prepare_epub(self.source, self.output)
        self.assertEqual(report["inline_notes"], 0)
        self.assertTrue(any("Shared note" in value for value in report["warnings"]))
        with zipfile.ZipFile(self.output) as z:
            tree = E.fromstring(z.read("OEBPS/Text/ch1.xhtml"))
            self.assertEqual(len(tree.xpath('.//h:aside', namespaces=NS)), 1)

    def test_toc_points_to_existing_unique_heading_anchors(self):
        book(self.source)
        prepare_epub(self.source, self.output)
        with zipfile.ZipFile(self.output) as z:
            ncx = E.fromstring(z.read("OEBPS/toc.ncx"))
            for href in ncx.xpath("//n:content/@src", namespaces=NS):
                name, fragment = resolve("OEBPS/toc.ncx", href)
                self.assertTrue(fragment)
                tree = E.fromstring(z.read(name))
                hits = tree.xpath("//*[@id=$id]", id=fragment)
                self.assertEqual(len(hits), 1)
                self.assertEqual(E.QName(hits[0]).localname, "h3")
            opf = E.fromstring(z.read("OEBPS/content.opf"))
            self.assertTrue(opf.xpath('o:guide/o:reference[@type="toc"]', namespaces=NS))
            self.assertEqual(opf.xpath('o:metadata/*[local-name()="identifier"]/text()', namespaces=NS), ["unchanged-book-identity"])

    def test_unknown_broken_fragment_is_reported_not_guessed(self):
        book(self.source, missing_fragment=True)
        report = prepare_epub(self.source, self.output)
        self.assertTrue(any("Unresolved TOC fragment" in value for value in report["warnings"]))
        with zipfile.ZipFile(self.output) as z:
            self.assertIn(b"ch2.xhtml#does-not-exist", z.read("OEBPS/toc.ncx"))

    def test_cover_metadata_is_bound_to_original_image(self):
        book(self.source)
        report = prepare_epub(self.source, self.output)
        self.assertTrue(report["cover_fixed"])
        with zipfile.ZipFile(self.output) as z:
            root = E.fromstring(z.read("OEBPS/content.opf"))
            self.assertEqual(root.xpath('o:metadata/o:meta[@name="cover"]/@content', namespaces=NS), ["cover-image"])
            self.assertEqual(root.xpath('o:manifest/o:item[@id="cover-image"]/@properties', namespaces=NS), ["cover-image"])

    def test_missing_cover_is_reported_without_inventing_one(self):
        book(self.source, no_cover=True)
        report = prepare_epub(self.source, self.output)
        self.assertFalse(report["cover_fixed"])
        self.assertTrue(any("Cover image could not" in value for value in report["warnings"]))

    def test_disabled_processor_does_not_write_any_output(self):
        book(self.source)
        report = prepare_epub(self.source, self.output, {"enabled": False})
        self.assertFalse(report["changed"])
        self.assertFalse(self.output.exists())

    def rewrite_chapter(self, before, after):
        with zipfile.ZipFile(self.source) as archive:
            data = {name: archive.read(name) for name in archive.namelist()}
        data["OEBPS/Text/ch1.xhtml"] = data["OEBPS/Text/ch1.xhtml"].replace(before.encode(), after.encode())
        with zipfile.ZipFile(self.source, "w") as archive:
            for name, value in data.items(): archive.writestr(name, value)

    def test_nested_footnote_reference_is_preserved(self):
        book(self.source)
        self.rewrite_chapter("Translator explanation", 'Translator <a epub:type="noteref" href="#n2">nested</a> explanation')
        report = prepare_epub(self.source, self.output)
        self.assertEqual(report["inline_notes"], 0)
        self.assertTrue(any("Nested note" in value for value in report["warnings"]))

    def test_external_link_to_note_substructure_is_preserved(self):
        book(self.source)
        self.rewrite_chapter('Translator explanation', '<span id="inner">Translator explanation</span>')
        self.rewrite_chapter('</h3>', '</h3><p><a href="#inner">Detail</a></p>')
        report = prepare_epub(self.source, self.output)
        self.assertEqual(report["inline_notes"], 0)
        self.assertTrue(any("Linked note substructure" in value for value in report["warnings"]))

    def test_source_overwrite_is_rejected(self):
        book(self.source)
        with self.assertRaises(ValueError):
            prepare_epub(self.source, self.source)


if __name__ == "__main__":
    unittest.main()
