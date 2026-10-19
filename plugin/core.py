"""Conservative EPUB preparation, independent of the calibre GUI."""
from __future__ import annotations

import copy
import hashlib
import json
import posixpath
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from lxml import etree as ET

H = "http://www.w3.org/1999/xhtml"
OP = "http://www.idpf.org/2007/opf"
EP = "http://www.idpf.org/2007/ops"
NCX = "http://www.daisy.org/z3986/2005/ncx/"
NS = {"h": H, "o": OP, "epub": EP, "n": NCX}
DEFAULTS = {"enabled": True, "inline_notes": True, "darken": True,
            "repair_toc": True, "repair_cover": True}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
NOTE_TYPES = {"footnote", "endnote", "rearnote"}
REF_CLASSES = {"duokan-footnote", "noteref", "footnote-ref", "footnote-reference"}
CSS_BASE = """/* Kindle Auto Prepare 1 */
.kap-note { display: block !important; position: static !important; opacity: 1 !important; visibility: visible !important; height: auto !important; max-height: none !important; width: auto !important; max-width: none !important; float: none !important; z-index: auto !important; font-size: 0.9em; line-height: 1.5; text-indent: 0; margin: 0.35em 0 0.65em; padding: 0; border: 0; background: transparent; text-shadow: none; }
.kap-note p { text-indent: 0; margin: 0.35em 0; line-height: 1.5; text-shadow: none; }
"""
CSS_DARK = """.kap-note, .kap-note * { color: #000 !important; text-shadow: none !important; }
ruby > rt { color: #000; font-weight: bold; }
"""


def local(element):
    return ET.QName(element).localname.lower() if isinstance(element.tag, str) else ""


def tokens(value):
    return set((value or "").lower().split())


def resolve(base, href):
    url = urlsplit(href)
    if url.scheme or url.netloc or url.query:
        return None
    path = unquote(url.path)
    name = posixpath.normpath(posixpath.join(posixpath.dirname(base), path)) if path else base
    if name.startswith("../") or name.startswith("/") or name in {"..", "."}:
        return None
    return name, unquote(url.fragment)


def relative(base, target, fragment=""):
    path = posixpath.relpath(target, posixpath.dirname(base) or ".")
    if target == base and fragment:
        path = ""
    result = quote(path, safe="/-._~")
    return result + ("#" + quote(fragment, safe="-._~:") if fragment else "")


def remove(element):
    parent = element.getparent()
    if parent is None:
        raise ValueError("Cannot remove a document root")
    previous = element.getprevious()
    if element.tail:
        if previous is not None:
            previous.tail = (previous.tail or "") + element.tail
        else:
            parent.text = (parent.text or "") + element.tail
    parent.remove(element)


def is_note(element):
    return bool(tokens(element.get("{" + EP + "}type")) & NOTE_TYPES
                or tokens(element.get("role")) & {"doc-footnote", "doc-endnote"}
                or "duokan-footnote-item" in tokens(element.get("class")))


def is_ref(element):
    return local(element) == "a" and bool(
        "noteref" in tokens(element.get("{" + EP + "}type"))
        or "doc-noteref" in tokens(element.get("role"))
        or tokens(element.get("class")) & REF_CLASSES)


def clean_popup(element):
    for child in element.iter():
        if not isinstance(child.tag, str):
            continue
        types = tokens(child.get("{" + EP + "}type"))
        if types & (NOTE_TYPES | {"noteref"}):
            remaining = types - NOTE_TYPES - {"noteref"}
            if remaining:
                child.set("{" + EP + "}type", " ".join(sorted(remaining)))
            else:
                child.attrib.pop("{" + EP + "}type", None)
        if tokens(child.get("role")) & {"doc-footnote", "doc-endnote", "doc-noteref", "doc-backlink"}:
            child.attrib.pop("role", None)
        child.attrib.pop("zy-footnote", None)


class Book:
    def __init__(self, source):
        self.source = Path(source)
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("EPUB contains duplicate ZIP paths")
            if sum(item.file_size for item in archive.infolist()) > 512 * 1024 * 1024:
                raise ValueError("EPUB is too large for automatic processing")
            self.infos = archive.infolist()
            self.comment = archive.comment
            self.data = {name: archive.read(name) for name in names}
        self.trees, self.dirty = {}, set()
        self.report = {"inline_notes": 0, "toc_targets_added": 0,
                       "toc_links_fixed": 0, "cover_fixed": False, "warnings": []}
        container = self.tree("META-INF/container.xml")
        roots = container.xpath("//*[local-name()='rootfile']/@full-path")
        if not roots or roots[0] not in self.data:
            raise ValueError("EPUB package document is missing")
        self.opf_name = roots[0]
        self.opf = self.tree(self.opf_name)
        self.manifest = self.opf.find("o:manifest", NS)
        self.metadata = self.opf.find("o:metadata", NS)
        self.spine = self.opf.find("o:spine", NS)
        if self.manifest is None or self.metadata is None or self.spine is None:
            raise ValueError("Unsupported EPUB package structure")
        self.items = {item.get("id"): item for item in self.manifest}
        self.documents = {}
        for item in self.manifest:
            if item.get("media-type") in {"application/xhtml+xml", "text/html"}:
                ref = resolve(self.opf_name, item.get("href", ""))
                if ref and ref[0] in self.data:
                    try:
                        self.documents[ref[0]] = self.tree(ref[0])
                    except ET.XMLSyntaxError:
                        self.warn("Unparseable XHTML left unchanged: " + ref[0])
        encryption = self.data.get("META-INF/encryption.xml")
        if encryption:
            tree = ET.fromstring(encryption, self.parser())
            for name in tree.xpath("//*[local-name()='CipherReference']/@URI"):
                if unquote(name) in self.documents:
                    raise ValueError("Encrypted book content is not processed")
        self.ids = {
            name: self.index_ids(tree) for name, tree in self.documents.items()
        }

    @staticmethod
    def parser():
        return ET.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)

    def tree(self, name):
        if name not in self.trees:
            self.trees[name] = ET.fromstring(self.data[name], self.parser())
        return self.trees[name]

    @staticmethod
    def index_ids(tree):
        result = defaultdict(list)
        for element in tree.iter():
            for key in ("id", "name"):
                if element.get(key):
                    result[element.get(key)].append(element)
        return result

    def warn(self, message):
        if len(self.report["warnings"]) < 100:
            self.report["warnings"].append(message)

    def unique_id(self, name, stem):
        used = {e.get("id") for e in self.documents[name].iter()}
        value, suffix = stem, 1
        while value in used:
            value = stem + "-" + str(suffix)
            suffix += 1
        return value

    def inline_notes(self):
        candidates = []
        all_links = Counter()
        for name, tree in self.documents.items():
            for anchor in tree.iter("{" + H + "}a"):
                destination = resolve(name, anchor.get("href", ""))
                if destination and destination[1]:
                    all_links[destination] += 1
                if not is_ref(anchor) or not destination:
                    continue
                if any(is_note(parent) for parent in anchor.iterancestors()):
                    self.warn("Nested note reference left unchanged: " + name)
                    continue
                target_name, fragment = destination
                elements = self.ids.get(target_name, {}).get(fragment, [])
                targets = []
                for element in elements:
                    ancestry = [element] + list(element.iterancestors())
                    outer = [e for e in ancestry if is_note(e)]
                    if outer and outer[-1] not in targets:
                        targets.append(outer[-1])
                paragraph = next((e for e in anchor.iterancestors() if local(e) == "p"), None)
                if len(targets) != 1 or paragraph is None:
                    self.warn("Ambiguous note reference left unchanged: " + name + "#" + fragment)
                    continue
                target = targets[0]
                if paragraph is target or target in paragraph.iterancestors():
                    continue
                if any(e.get("{http://www.w3.org/XML/1998/namespace}base") for e in target.iter()):
                    self.warn("Note with xml:base left unchanged: " + name)
                    continue
                candidates.append((name, anchor, paragraph, target_name, fragment, target))
        usage = Counter(id(row[5]) for row in candidates)
        navigation, _ = self.navigation()
        protected = {resolve(base, node.get(key, "")) for base, node, key, label in navigation}
        last_after = {}
        for name, anchor, paragraph, target_name, fragment, target in candidates:
            if usage[id(target)] != 1 or all_links[(target_name, fragment)] != 1:
                self.warn("Shared note left unchanged: " + target_name + "#" + fragment)
                continue
            if (target_name, fragment) in protected or (target_name != name and (target_name, "") in protected):
                self.warn("Note referenced by the TOC left unchanged: " + target_name + "#" + fragment)
                continue
            descendants = list(target.iterdescendants())
            if any(is_ref(child) for child in descendants):
                self.warn("Nested note reference left unchanged: " + target_name + "#" + fragment)
                continue
            if any(is_note(child) and child.get("id") != fragment for child in descendants):
                self.warn("Nested note body left unchanged: " + target_name + "#" + fragment)
                continue
            if any(child.get("id") != fragment and all_links[(target_name, child.get("id"))]
                   for child in descendants if child.get("id")):
                self.warn("Linked note substructure left unchanged: " + target_name + "#" + fragment)
                continue
            if any(parent.get("{http://www.w3.org/XML/1998/namespace}base")
                   for parent in list(target.iterancestors()) + list(anchor.iterancestors())):
                self.warn("Note with inherited xml:base left unchanged: " + target_name)
                continue
            clone = copy.deepcopy(target)
            known_items = clone.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' duokan-footnote-item ')]")
            if len(known_items) == 1 and local(clone) == "aside":
                item = known_items[0]
                container = ET.Element("{" + H + "}div")
                container.text = item.text
                for child in item:
                    container.append(copy.deepcopy(child))
                clone = container
            clone.tag = "{" + H + "}div"
            clone.set("class", "kap-note")
            stem = "kap-note-" + hashlib.sha256((target_name + "#" + fragment).encode()).hexdigest()[:12]
            clone.set("id", self.unique_id(name, stem))
            for child in clone.iterdescendants():
                if child.get("id"):
                    child.set("id", self.unique_id(name, stem + "-" + child.get("id")))
                if local(child) == "a":
                    destination = resolve(target_name, child.get("href", ""))
                    if destination == (name, anchor.get("id")):
                        child.tag = "{" + H + "}span"
                        child.attrib.pop("href", None)
                for key in ("src", "href", "{http://www.w3.org/1999/xlink}href"):
                    value = child.get(key)
                    destination = resolve(target_name, value) if value else None
                    if destination and target_name != name:
                        child.set(key, relative(name, *destination))
            clean_popup(clone)
            clone.tail = "\n"
            insertion = last_after.get(paragraph, paragraph)
            insertion.addnext(clone)
            last_after[paragraph] = clone
            remove(target)
            anchor.tag = "{" + H + "}span"
            anchor.attrib.pop("href", None)
            anchor.set("class", "kap-note-ref")
            clean_popup(anchor)
            for parent in paragraph.iterancestors():
                if local(parent) == "note":
                    parent.tag = "{" + H + "}div"
            self.dirty.update({name, target_name})
            self.report["inline_notes"] += 1
        self.ids = {name: self.index_ids(tree) for name, tree in self.documents.items()}

    def navigation(self):
        records, html_toc = [], []
        for item in self.manifest:
            destination = resolve(self.opf_name, item.get("href", ""))
            if not destination or destination[0] not in self.data:
                continue
            if item.get("media-type") == "application/x-dtbncx+xml":
                name = destination[0]
                try:
                    tree = self.tree(name)
                    for point in tree.findall(".//n:navPoint", NS):
                        node = point.find("n:content", NS)
                        label = point.find("n:navLabel/n:text", NS)
                        if node is not None:
                            records.append((name, node, "src", label.text if label is not None else ""))
                except ET.XMLSyntaxError:
                    self.warn("Unparseable NCX left unchanged: " + name)
        for name, tree in self.documents.items():
            for element in tree.iter():
                if local(element) in {"nav", "section"} and (
                    "toc" in tokens(element.get("{" + EP + "}type"))
                    or "doc-toc" in tokens(element.get("role"))
                ):
                    html_toc.append((name, element))
                    for anchor in element.iter("{" + H + "}a"):
                        records.append((name, anchor, "href", "".join(anchor.itertext())))
        return records, html_toc

    def repair_toc(self):
        records, html_toc = self.navigation()
        mapping = {}
        for base, node, key, label in records:
            destination = resolve(base, node.get(key, ""))
            if not destination:
                continue
            name, fragment = destination
            if name not in self.documents:
                self.warn("Missing TOC document left unchanged: " + name)
                continue
            if fragment and len(self.ids[name].get(fragment, [])) == 1:
                continue
            headings = [e for e in self.documents[name].iter()
                        if local(e) in HEADINGS and not any(is_note(a) for a in e.iterancestors())
                        and "sigil_not_in_toc" not in tokens(e.get("class"))]
            if fragment:
                compact = lambda text: re.sub(r"\s+", "", text or "")
                matches = [e for e in headings if compact("".join(e.itertext())) == compact(label)]
                if len(matches) != 1:
                    self.warn("Unresolved TOC fragment left unchanged: " + name + "#" + fragment)
                    continue
                heading = matches[0]
            elif headings:
                heading = headings[0]
            else:
                body = self.documents[name].find("h:body", NS)
                heading = next((e for e in body if "".join(e.itertext()).strip()), body) if body is not None else None
                if heading is None:
                    self.warn("Empty TOC document left unchanged: " + name)
                    continue
            anchor = heading.get("id")
            if not anchor or len(self.ids[name].get(anchor, [])) > 1:
                stem = "kap-toc-" + hashlib.sha256(name.encode()).hexdigest()[:12]
                anchor = self.unique_id(name, stem)
                heading.set("id", anchor)
                self.dirty.add(name)
                self.ids[name][anchor] = [heading]
                self.report["toc_targets_added"] += 1
            node.set(key, relative(base, name, anchor))
            self.dirty.add(base)
            mapping[destination] = (name, anchor)
            self.report["toc_links_fixed"] += 1
        if mapping:
            for name, tree in self.documents.items():
                for link in tree.iter("{" + H + "}a"):
                    destination = resolve(name, link.get("href", ""))
                    if destination in mapping:
                        link.set("href", relative(name, *mapping[destination]))
                        self.dirty.add(name)
        guide = self.opf.find("o:guide", NS)
        if html_toc and (guide is None or not any(e.get("type") == "toc" for e in guide)):
            name, element = html_toc[0]
            anchor = element.get("id")
            if not anchor:
                anchor = self.unique_id(name, "kap-toc")
                element.set("id", anchor)
                self.dirty.add(name)
            if guide is None:
                guide = ET.SubElement(self.opf, "{" + OP + "}guide")
            ET.SubElement(guide, "{" + OP + "}reference", {
                "type": "toc", "title": "Table of Contents",
                "href": relative(self.opf_name, name, anchor)})
            self.dirty.add(self.opf_name)

    def repair_cover(self):
        images = {}
        for ident, item in self.items.items():
            destination = resolve(self.opf_name, item.get("href", ""))
            if destination and destination[0] in self.data and item.get("media-type", "").startswith("image/"):
                images[ident] = (item, destination[0])
        explicit = [ident for ident, (item, name) in images.items()
                    if "cover-image" in tokens(item.get("properties"))]
        metas = self.metadata.findall("o:meta[@name='cover']", NS)
        legacy = [e.get("content") for e in metas if e.get("content") in images]
        choices = explicit or legacy
        if not choices:
            guide = self.opf.find("o:guide", NS)
            refs = [e.get("href") for e in (guide if guide is not None else []) if e.get("type") == "cover"]
            for href in refs:
                destination = resolve(self.opf_name, href)
                if destination and destination[0] in self.documents:
                    tree = self.documents[destination[0]]
                    targets = [resolve(destination[0], img.get("src", ""))
                               for img in tree.iter("{" + H + "}img")]
                    found = [ident for ident, (item, name) in images.items()
                             if (name, "") in targets]
                    if len(found) == 1:
                        choices = found
        if len(set(choices)) != 1:
            self.warn("Cover image could not be identified unambiguously; original kept")
            return
        ident = choices[0]
        if not metas:
            ET.SubElement(self.metadata, "{" + OP + "}meta", {"name": "cover", "content": ident})
            self.dirty.add(self.opf_name)
            self.report["cover_fixed"] = True
        elif any(e.get("content") != ident for e in metas):
            for element in metas:
                element.set("content", ident)
            self.dirty.add(self.opf_name)
            self.report["cover_fixed"] = True
        if self.opf.get("version", "").startswith("3"):
            item = images[ident][0]
            properties = tokens(item.get("properties"))
            if "cover-image" not in properties:
                item.set("properties", " ".join(sorted(properties | {"cover-image"})))
                self.dirty.add(self.opf_name)
                self.report["cover_fixed"] = True
        self.report["cover_image"] = images[ident][1]

    def add_styles(self, darken):
        has_notes = any(tree.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' kap-note ')]")
                        for tree in self.documents.values())
        has_ruby = any(any(local(e) == "rt" for e in tree.iter()) for tree in self.documents.values())
        if not has_notes and not (darken and has_ruby):
            return
        css = (CSS_BASE + (CSS_DARK if darken else "")).encode("utf-8")
        css_name = posixpath.join(posixpath.dirname(self.opf_name), "Styles/kindle-auto-prepare.css")
        if css_name in self.data and not self.data[css_name].startswith(b"/* Kindle Auto Prepare"):
            self.warn("Reserved stylesheet name already used; styles left unchanged")
            return
        if self.data.get(css_name) != css:
            self.data[css_name] = css
            self.dirty.add(css_name)
        href = relative(self.opf_name, css_name)
        if not any(e.get("href") == href for e in self.manifest):
            ident, number = "kindle-auto-prepare-css", 1
            while ident in self.items:
                ident = "kindle-auto-prepare-css-" + str(number)
                number += 1
            ET.SubElement(self.manifest, "{" + OP + "}item",
                          {"id": ident, "href": href, "media-type": "text/css"})
            self.dirty.add(self.opf_name)
        for name, tree in self.documents.items():
            head = tree.find("h:head", NS)
            if head is None:
                continue
            if not any(resolve(name, e.get("href", "")) == (css_name, "") for e in head.iter("{" + H + "}link")):
                ET.SubElement(head, "{" + H + "}link", {
                    "rel": "stylesheet", "type": "text/css", "href": relative(name, css_name)})
                self.dirty.add(name)

    def save(self, destination):
        if Path(destination).resolve() == self.source.resolve():
            raise ValueError("Source EPUB is never overwritten")
        for name in self.dirty:
            if name in self.trees:
                tree = self.trees[name]
                doctype = tree.getroottree().docinfo.doctype or None
                self.data[name] = ET.tostring(tree, encoding="utf-8", xml_declaration=True, doctype=doctype)
                ET.fromstring(self.data[name], self.parser())
        infos = {item.filename: item for item in self.infos}
        with zipfile.ZipFile(destination, "w") as archive:
            archive.comment = self.comment
            archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
            for name, data in self.data.items():
                if name == "mimetype":
                    continue
                if name in infos:
                    archive.writestr(infos[name], data)
                else:
                    archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(destination) as archive:
            if archive.testzip() is not None:
                raise ValueError("Output ZIP validation failed")


def prepare_epub(source, destination, settings=None):
    options = dict(DEFAULTS)
    options.update(settings or {})
    if not options["enabled"]:
        return {"changed": False, "disabled": True}
    book = Book(source)
    if options["inline_notes"]:
        book.inline_notes()
    if options["repair_toc"]:
        book.repair_toc()
    if options["repair_cover"]:
        book.repair_cover()
    book.add_styles(options["darken"])
    book.report["changed"] = bool(book.dirty)
    book.report["source_sha256"] = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    if book.dirty:
        book.save(destination)
    return book.report
