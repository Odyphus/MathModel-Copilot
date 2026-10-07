"""Read an actual DOCX and compare it with current registered paper sources.

This intentionally accepts a small, deterministic Markdown subset. It does not
accept self-reported expected text or an arbitrary OMML hash as evidence. Word
rendering, page inspection, and PDF derivation remain separate document checks.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
NS = {"w": W, "m": M, "a": A, "r": R}
CLAIM = re.compile(r"\[\[claim:[A-Za-z0-9_.:@-]+\]\]")
FIGURE = re.compile(r"\[\[figure:(\d+)\]\]\Z")
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^\s)]+)\)\Z")


def _norm(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)))


def _numbers(text):
    from copilot_runtime import numeric_tokens
    return numeric_tokens(unicodedata.normalize("NFKC", str(text)))


def _text_block(text):
    # Keep number token order and boundaries before formatting whitespace is
    # normalized. In particular, 18 2.81 must never equal 182.81.
    return {"kind": "text", "text": _norm(text), "numbers": _numbers(text)}


def _table_block(rows):
    return {"kind": "table", "rows": [[_norm(cell) for cell in row] for row in rows],
            "numbers": [[_numbers(cell) for cell in row] for row in rows]}


def _inline(text):
    text = CLAIM.sub("", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text.strip()


def _math_norm(text):
    # Token equality, not mathematical equivalence. Braces and argument order
    # remain significant, including denominator/subscript/radical structure.
    for before, after in ((r"\sum", "∑"), (r"\in", "∈"), (r"\leq", "≤"),
                          (r"\le", "≤"), (r"\pm", "±")):
        text = text.replace(before, after)
    return _norm(text)


def _children(node, allowed, context):
    """Do not silently discard an unrecognized child of a visible container."""
    for child in node:
        if child.tag not in allowed:
            raise ValueError(f"Unsupported DOCX {context} node: {child.tag}")


def _run_text(node, *, math=False):
    text_tag = "{" + (M if math else W) + "}t"
    properties = {"{" + W + "}rPr"} | ({"{" + M + "}rPr"} if math else set())
    parts = []
    for item in node:
        if item.tag in properties:
            continue
        if item.tag == "{" + W + "}drawing" and not math:
            _drawing(item)
            continue
        if len(item):
            raise ValueError("Unsupported nested DOCX run content: " + item.tag)
        if item.tag == text_tag:
            parts.append(item.text or "")
        elif item.tag == "{" + W + "}tab":
            parts.append("\t")
        elif item.tag == "{" + W + "}cr":
            parts.append("\n")
        elif item.tag == "{" + W + "}br":
            if item.get("{" + W + "}type") not in {None, "textWrapping", "page", "column"}:
                raise ValueError("Unsupported DOCX break type")
            # An explicit break must not concatenate two numeric tokens, even
            # when it moves the remainder onto another page or column.
            parts.append("\n")
        elif item.tag == "{" + W + "}noBreakHyphen":
            parts.append("-")
        elif item.tag == "{" + W + "}lastRenderedPageBreak":
            # Renderer annotation, not an authored character/break.
            continue
        else:
            # w:sym uses a font-specific glyph identifier, not a dependable
            # Unicode value. Fields/soft hyphens also need rendering context.
            raise ValueError("Unsupported DOCX run content: " + item.tag)
    return "".join(parts)


def _drawing(node):
    """Keep the existing embedded picture path; reject other visible content."""
    q = lambda namespace, names: {"{" + namespace + "}" + name for name in names.split()}
    grammar = {
        "{" + W + "}drawing": q(WP, "inline"),
        "{" + WP + "}inline": q(WP, "extent effectExtent docPr cNvGraphicFramePr") | q(A, "graphic"),
        "{" + WP + "}cNvGraphicFramePr": q(A, "graphicFrameLocks"),
        "{" + A + "}graphic": q(A, "graphicData"),
        "{" + A + "}graphicData": q(PIC, "pic"),
        "{" + PIC + "}pic": q(PIC, "nvPicPr blipFill spPr"),
        "{" + PIC + "}nvPicPr": q(PIC, "cNvPr cNvPicPr"),
        "{" + PIC + "}cNvPicPr": q(A, "picLocks"),
        "{" + PIC + "}blipFill": q(A, "blip stretch"),
        "{" + A + "}stretch": q(A, "fillRect"),
        "{" + PIC + "}spPr": q(A, "xfrm prstGeom"),
        "{" + A + "}xfrm": q(A, "off ext"),
        "{" + A + "}prstGeom": q(A, "avLst"),
    }
    for item in node.iter():
        _children(item, grammar.get(item.tag, set()), "drawing")
    for tag in ((WP, "inline"), (A, "graphic"), (A, "graphicData"), (PIC, "pic"), (A, "blip")):
        matches = list(node.iter("{" + tag[0] + "}" + tag[1]))
        if len(matches) != 1:
            raise ValueError("Unsupported DOCX drawing; requires one embedded inline picture")
        if tag == (A, "graphicData") and matches[0].get("uri") != PIC:
            raise ValueError("Unsupported DOCX drawing graphicData URI")


def omml_expression(node):
    """A deliberately strict, documented linear form of supported OMML."""
    if not node.tag.startswith("{" + M + "}"):
        raise ValueError("Unsupported OMML namespace: " + node.tag)
    tag = node.tag.split("}")[-1]
    expressions = {"r", "sSub", "sSup", "sSubSup", "f", "rad", "bar", "nary"}
    containers = {"oMath", "oMathPara", "e", "num", "den", "sub", "sup", "deg"}
    grammar = {"sSub": {"e", "sub"}, "sSup": {"e", "sup"}, "sSubSup": {"e", "sub", "sup"},
               "f": {"num", "den"}, "rad": {"deg", "e"}, "bar": {"e"}, "nary": {"sub", "sup", "e"}}
    properties = {"{" + M + "}ctrlPr"}
    if tag in grammar or tag == "oMathPara":
        properties.add("{" + M + "}" + tag + "Pr")
    if tag in containers:
        allowed = {"oMath"} if tag == "oMathPara" else expressions
        properties.add("{" + M + "}argPr")
        _children(node, {"{" + M + "}" + name for name in allowed} | properties, "math container")
    elif tag in grammar:
        _children(node, {"{" + M + "}" + name for name in grammar[tag]} | properties, "math container")
        for name in grammar[tag]:
            if len(node.findall("{" + M + "}" + name)) > 1:
                raise ValueError("Duplicate native math argument: " + name)
    child = lambda name: next((n for n in node if n.tag == "{" + M + "}" + name), None)
    value = lambda name: omml_expression(child(name)) if child(name) is not None else ""
    if tag in containers:
        return "".join(omml_expression(n) for n in node if n.tag not in properties)
    if tag == "r":
        return _run_text(node, math=True)
    if tag == "sSub":
        return value("e") + "_{" + value("sub") + "}"
    if tag == "sSup":
        return value("e") + "^{" + value("sup") + "}"
    if tag == "sSubSup":
        return value("e") + "_{" + value("sub") + "}^{" + value("sup") + "}"
    if tag == "f":
        return r"\frac{" + value("num") + "}{" + value("den") + "}"
    if tag == "rad":
        degree = value("deg")
        return r"\sqrt" + ("[" + degree + "]" if degree else "") + "{" + value("e") + "}"
    if tag == "bar":
        position = node.find("m:barPr/m:pos", NS)
        if position is not None and position.get("{" + M + "}val") not in {None, "top"}:
            raise ValueError("Only top-bar OMML is supported by the source audit")
        return r"\overline{" + value("e") + "}"
    if tag == "nary":
        symbol = node.find("m:naryPr/m:chr", NS)
        if symbol is None or not symbol.get("{" + M + "}val"):
            raise ValueError("N-ary OMML requires an explicit operator")
        return (symbol.get("{" + M + "}val") + ("_{" + value("sub") + "}" if value("sub") else "")
                + ("^{" + value("sup") + "}" if value("sup") else "") + "{" + value("e") + "}")
    raise ValueError("Unsupported OMML node; no equivalence assumed: " + tag)


def _paragraph_text(node):
    """Read the supported inline grammar in order, including table/code paths."""
    if node.find("w:pPr/w:numPr", NS) is not None:
        raise ValueError("Implicit Word numbering is not an explicit section projection")
    parts = []
    def walk(container, hyperlink=False):
        for item in container:
            if item.tag == "{" + W + "}pPr" and not hyperlink:
                continue
            if item.tag == "{" + W + "}r":
                parts.append(_run_text(item))
            elif item.tag == "{" + W + "}hyperlink" and not hyperlink:
                walk(item, hyperlink=True)
            elif item.tag in {"{" + W + "}" + tag for tag in ("bookmarkStart", "bookmarkEnd", "proofErr")}:
                _children(item, set(), "range marker")
            elif item.tag in {"{" + M + "}oMath", "{" + M + "}oMathPara"}:
                omml_expression(item)  # Validate before separately projecting math.
            else:
                raise ValueError("Unsupported DOCX paragraph content: " + item.tag)
    walk(node)
    return "".join(parts)


def read_docx_blocks(path):
    """Extract ordered native paragraphs, table cells, equations and images."""
    blocks = []
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError("DOCX CRC failure: " + bad)
        root = ET.fromstring(archive.read("word/document.xml"))
        if "word/styles.xml" in archive.namelist():
            styles = ET.fromstring(archive.read("word/styles.xml"))
            for item in styles.iter():
                if item.tag not in {"{" + W + "}vanish", "{" + W + "}webHidden"}:
                    continue
                value = str(item.get("{" + W + "}val", "true")).lower()
                # A small readback validator must not assume that a paragraph,
                # character, inherited, default or table style is visible.
                # Conservatively reject even unused hidden-style definitions;
                # explicit false is safe, unknown on/off values are not.
                if value not in {"0", "false", "off"}:
                    raise ValueError("Hidden/uncertain Word styles or defaults are outside visible source-audit support")
        relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        targets = {}
        for row in relationships:
            if row.get("TargetMode") == "External":
                continue
            targets[row.get("Id")] = row.get("Target", "")
        body = root.find("w:body", NS)
        if body is None:
            raise ValueError("DOCX lacks a native body")
        disallowed = {"altChunk", "txbxContent", "footnoteReference", "endnoteReference", "ins", "del"}
        if any(n.tag.split("}")[-1] in disallowed for n in body.iter()):
            raise ValueError("Unsupported embedded/hidden or revision content in DOCX body")
        if body.findall(".//w:vanish", NS) or body.findall(".//w:webHidden", NS):
            raise ValueError("Hidden text cannot establish visible section coverage")
        for node in body:
            if node.tag == "{" + W + "}sectPr":
                continue
            if node.tag == "{" + W + "}tbl":
                if len(list(node.iter("{" + W + "}tbl"))) != 1:
                    raise ValueError("Nested tables are not supported")
                if node.findall(".//a:blip", NS) or node.findall(".//m:oMath", NS):
                    raise ValueError("Table images/math require a separately supported mapping")
                # Enumerate the native table structure rather than silently
                # skipping visible content controls or other cell containers.
                if any(n.tag not in {"{" + W + "}" + x for x in ("tblPr", "tblGrid", "tr")} for n in node):
                    raise ValueError("Unsupported native table container")
                for row in node.findall("w:tr", NS):
                    if any(n.tag not in {"{" + W + "}" + x for x in ("trPr", "tblPrEx", "tc")} for n in row):
                        raise ValueError("Unsupported native table row container")
                    for cell in row.findall("w:tc", NS):
                        if any(n.tag not in {"{" + W + "}" + x for x in ("tcPr", "p")} for n in cell):
                            raise ValueError("Unsupported native table cell container")
                rows = [["\n".join(_paragraph_text(p) for p in cell.findall("w:p", NS))
                         for cell in row.findall("w:tc", NS)] for row in node.findall("w:tr", NS)]
                blocks.append(_table_block(rows))
                continue
            if node.tag != "{" + W + "}p":
                raise ValueError("Unsupported DOCX body block: " + node.tag)
            if node.findall(".//w:vanish", NS) or node.findall(".//w:webHidden", NS):
                raise ValueError("Hidden text cannot establish visible section coverage")
            text = _paragraph_text(node)
            maths, images = node.findall(".//m:oMath", NS), node.findall(".//a:blip", NS)
            if maths:
                if len(maths) != 1 or images:
                    raise ValueError("Only one standalone native equation per paragraph is supported")
                expression = omml_expression(maths[0])
                blocks.append({"kind": "math", "expression": _math_norm(expression), "text": _norm(text),
                               "numbers": _numbers(expression), "text_numbers": _numbers(text)})
            elif images:
                if len(images) != 1 or text.strip():
                    raise ValueError("Only standalone images are supported")
                target = targets.get(images[0].get("{" + R + "}embed"))
                if not target or ".." in PurePosixPath(target).parts or PurePosixPath(target).is_absolute():
                    raise ValueError("Image is not an embedded DOCX media file")
                member = "word/" + target
                if not member.startswith("word/media/"):
                    raise ValueError("Image target lies outside native DOCX media")
                blocks.append({"kind": "image", "sha256": hashlib.sha256(archive.read(member)).hexdigest().upper()})
            elif text.strip():
                style = node.find("w:pPr/w:pStyle", NS)
                if style is not None and style.get("{" + W + "}val") in {"CopilotSourceCode", "CUMCMSourceCode"}:
                    blocks.append({"kind": "code", "text": text.replace("\r\n", "\n").rstrip("\n")})
                else:
                    blocks.append(_text_block(text))
    return blocks


def _bound_object_file(root, cp, source_id, path, kinds):
    from copilot_runtime import bind_file, object_errors
    obj = cp.get("objects", {}).get(source_id, {})
    if obj.get("kind") not in kinds:
        raise ValueError("Unsupported bound source object: " + str(source_id))
    issues = object_errors(root, cp, source_id)
    if issues:
        raise ValueError("; ".join(issues))
    actual = bind_file(root, path)
    if not any(item.get("path") == path and str(item.get("sha256", "")).upper() == actual["sha256"] for item in obj.get("files", [])):
        raise ValueError("Source file is not bound by the current declared object: " + path)
    return actual


def _table_cells(line):
    if not line.strip().startswith("|") or not line.strip().endswith("|"):
        raise ValueError("Tables require explicit leading and trailing pipes")
    return [_inline(cell) for cell in line.strip()[1:-1].split("|")]


def _parse_markdown(text, image_lookup):
    """Parse the explicit small source subset; never execute embedded markup."""
    lines, blocks, index = text.splitlines(), [], 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("```") or line.startswith("~~~"):
            raise ValueError("Freeform fenced blocks are not document sources; use a bound source_code supplement")
        if line.startswith("$$"):
            match = re.fullmatch(r"\$\$(.+?)\$\$\s*(.*)", line)
            if not match:
                raise ValueError("Native math requires one explicit $$ expression $$ source line")
            blocks.append({"kind": "math", "expression": _math_norm(match.group(1)), "text": _norm(_inline(match.group(2))),
                           "numbers": _numbers(match.group(1)), "text_numbers": _numbers(_inline(match.group(2)))})
            index += 1
            continue
        if line.startswith("|"):
            if index + 1 >= len(lines) or not re.fullmatch(r"\|[\s:|\-]+\|", lines[index + 1].strip()):
                raise ValueError("Native table source needs a Markdown separator row")
            rows = [_table_cells(line)]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_table_cells(lines[index]))
                index += 1
            if any(len(row) != len(rows[0]) for row in rows):
                raise ValueError("Table source has inconsistent column counts")
            blocks.append(_table_block(rows))
            continue
        match = IMAGE.fullmatch(line)
        if match:
            blocks.append({"kind": "image", "sha256": image_lookup(match.group(2))})
            index += 1
            continue
        paragraph = []
        while index < len(lines) and lines[index].strip():
            current = lines[index].strip()
            if paragraph and (current.startswith(("|", "$$", "#")) or IMAGE.fullmatch(current)):
                break
            if "<" in current and re.search(r"</?[A-Za-z!]", current):
                raise ValueError("HTML is not supported in a visible paper projection")
            paragraph.append(re.sub(r"^#{1,6}\s+", "", current))
            index += 1
            if current.startswith("#"):
                break
        value = _inline("\n".join(paragraph))
        if value:
            blocks.append(_text_block(value))
    return blocks


def paper_source_blocks(root, cp, section_ids, contract):
    """Derive canonical blocks from live sections; also usable by a renderer."""
    from copilot_runtime import bind_file, object_errors, safe_path
    from copilot_delivery import _section_errors
    from copilot_section import section_projection
    if not isinstance(contract, dict) or contract.get("version") != "0.1":
        raise ValueError("Paper source contract version must be 0.1")
    if set(contract) - {"version", "sections", "supplements"}:
        raise ValueError("Unknown/self-reported paper source fields are not accepted")
    order = contract.get("sections")
    if not isinstance(order, list) or not order or len(order) != len(set(order)) or set(order) != set(section_ids):
        raise ValueError("Paper source order must include every declared Section exactly once")
    files, dependencies, blocks, maps = [], [], [], []
    for section_id in order:
        obj = cp.get("objects", {}).get(section_id, {})
        if obj.get("kind") != "PaperSection" or obj.get("status") != "verified":
            raise ValueError("Paper source Section must be current and verified: " + section_id)
        issues = object_errors(root, cp, section_id)
        if issues:
            raise ValueError("; ".join(issues))
        payload = obj["payload"]
        path = payload["path"]
        text = safe_path(root, path).read_text(encoding="utf-8")
        # Revalidate content, not just an outer status/hash label.
        issues = _section_errors(root, cp, text, payload["claim_ids"],
                                 source_bindings=payload.get("source_bindings"), structure=payload.get("structure"))
        if issues:
            raise ValueError("; ".join(issues))
        files.append(bind_file(root, path))
        dependencies.append(section_id)
        figure_paths = {}
        for item in payload.get("structure", []):
            if item.get("kind") != "figure":
                continue
            artifact = cp.get("objects", {}).get(item.get("artifact_id"), {})
            paths = artifact.get("files", [])
            if len(paths) != 1:
                raise ValueError("Figure ArtifactRecord must bind one actual image file")
            record = _bound_object_file(root, cp, item["artifact_id"], paths[0]["path"], {"ArtifactRecord"})
            figure_paths[record["path"]] = record["sha256"]
            files.append(record)
            dependencies.append(item["artifact_id"])
        def image_lookup(reference):
            if reference not in figure_paths:
                raise ValueError("Image path is not bound by this Section's figure ArtifactRecord: " + reference)
            return figure_paths[reference]
        projection = section_projection(cp, text, payload.get("source_bindings"), payload.get("structure"), root=root)
        if not isinstance(projection, str):
            raise ValueError("Section projection did not return visible source text")
        derived = _parse_markdown(CLAIM.sub("", projection), image_lookup)
        maps.append({"section_id": section_id, "path": path, "first_block": len(blocks), "block_count": len(derived)})
        blocks.extend(derived)
    listed_paths = set()
    for item in contract.get("supplements", []):
        if isinstance(item, dict) and item.get("kind") == "file_list":
            if set(item) != {"kind", "source_id", "paths"} or not isinstance(item["paths"], list) or not item["paths"]:
                raise ValueError("file_list requires a current source_id and nonempty bound paths")
            for relative in item["paths"]:
                if not isinstance(relative, str) or relative in listed_paths:
                    raise ValueError("file_list paths must be unique strings")
                record = _bound_object_file(root, cp, item["source_id"], relative,
                    {"ProblemContract", "DataContract", "CodeManifest", "ValidationPlan", "ArtifactRecord", "RunRecord"})
                listed_paths.add(relative)
                files.append(record)
                blocks.append(_text_block("文件：" + relative))
            dependencies.append(item["source_id"])
            continue
        if not isinstance(item, dict) or set(item) != {"kind", "source_id", "path"} or item["kind"] != "source_code":
            raise ValueError("Only bound file_list or source_code supplements are supported")
        record = _bound_object_file(root, cp, item["source_id"], item["path"], {"CodeManifest", "ValidationPlan"})
        text = safe_path(root, item["path"]).read_text(encoding="utf-8-sig").replace("\r\n", "\n").rstrip("\n")
        blocks.extend([_text_block("源程序：" + item["path"]), {"kind": "code", "text": text}])
        files.append(record)
        dependencies.append(item["source_id"])
    return {"blocks": blocks, "section_map": maps, "files": list({f["path"]: f for f in files}.values()),
            "dependencies": list(dict.fromkeys(dependencies))}


def audit_paper_source(root, cp, section_ids, docx_path, contract):
    """Return actual source/DOCX findings without changing state or any file."""
    from copilot_runtime import bind_file, safe_path
    errors, expected, actual, files, dependencies, mapping = [], [], [], [], [], []
    try:
        root = Path(root).resolve()
        path = Path(docx_path)
        relative = path.resolve().relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
        path = safe_path(root, relative)
        if path.suffix.lower() != ".docx":
            raise ValueError("Source audit requires the actual editable DOCX master")
        derived = paper_source_blocks(root, cp, section_ids, contract)
        expected, files, dependencies, mapping = derived["blocks"], derived["files"], derived["dependencies"], derived["section_map"]
        before = bind_file(root, relative)
        actual = read_docx_blocks(path)
        after = bind_file(root, relative)
        if before != after:
            errors.append("DOCX changed during source readback")
        files.append(before)
        if len(expected) != len(actual):
            errors.append(f"Native body block count differs from registered sources: {len(actual)} != {len(expected)}")
        for index, (wanted, found) in enumerate(zip(expected, actual)):
            if wanted != found:
                errors.append(f"Native body block {index} differs from the registered source ({wanted['kind']} vs {found['kind']})")
    except (ValueError, OSError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, ET.ParseError) as exc:
        errors.append(str(exc))
    return {"passed": not errors, "status": "pass" if not errors else "fail", "errors": errors,
            "checker": "ordered_registered_sections_to_native_docx", "source_block_count": len(expected),
            "actual_block_count": len(actual), "section_map": mapping, "files": files, "dependencies": dependencies,
            "scope": "Exact normalized native body/table/math-token/image/source-code correspondence; not semantic proof, PDF rendering, or human review"}
