"""EPUB chapter-preserving translator with portable, user-owned checkpoints."""
from __future__ import annotations
import hashlib
import io
import json
import re
import time
import zipfile
from dataclasses import dataclass
from typing import Callable

from lxml import etree

MAX_EPUB_BYTES = 60 * 1024 * 1024
MAX_ARCHIVE_BYTES = 250 * 1024 * 1024
SKIP_ELEMENTS = {'script', 'style', 'code', 'pre', 'svg', 'math'}
HEBREW = re.compile(r'[\u0590-\u05ff]')
LATIN_WORDS = re.compile(r'[A-Za-z]+')

class BookError(ValueError):
    pass

class QuotaStop(RuntimeError):
    pass

@dataclass
class Node:
    key: str
    original: str
    path: str
    section: str
    element: object
    attr: str


def validate_book(data: bytes) -> None:
    if not data or len(data) > MAX_EPUB_BYTES:
        raise BookError('קובץ ריק או גדול מ־60MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if len(z.infolist()) > 5000 or sum(i.file_size for i in z.infolist()) > MAX_ARCHIVE_BYTES:
                raise BookError('ארכיון EPUB גדול מדי או מכיל יותר מדי קבצים.')
            if 'mimetype' not in z.namelist() or z.read('mimetype').strip() != b'application/epub+zip':
                raise BookError('הקובץ אינו EPUB תקני, או שהוא מוגן בצורה שאינה נתמכת.')
            if 'META-INF/encryption.xml' in z.namelist():
                raise BookError('זוהתה הצפנה ב־EPUB. יש להעלות ספר ללא DRM.')
    except (zipfile.BadZipFile, RuntimeError) as e:
        raise BookError('לא ניתן לפתוח את קובץ ה־EPUB.') from e


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1].lower() if isinstance(tag, str) else ''


def _eligible(text: str | None) -> bool:
    if not text or not text.strip():
        return False
    s = text.strip()
    if s.startswith(('http://', 'https://', 'mailto:')):
        return False
    return len(LATIN_WORDS.findall(s)) > 0


def _content_paths(z: zipfile.ZipFile) -> list[str]:
    """Use package OPF spine order, then any remaining XHTML (nav, notes)."""
    names = set(z.namelist())
    try:
        container = etree.fromstring(z.read('META-INF/container.xml'))
        rootfiles = container.xpath('//*[local-name()="rootfile"]/@full-path')
        opf_path = rootfiles[0]
        opf = etree.fromstring(z.read(opf_path))
        from posixpath import dirname, normpath, join
        basedir = dirname(opf_path)
        idmap = {}
        for item in opf.xpath('//*[local-name()="manifest"]/*[local-name()="item"]'):
            if item.get('media-type') == 'application/xhtml+xml':
                idmap[item.get('id')] = normpath(join(basedir, item.get('href').split('#')[0]))
        ordered = [idmap[item.get('idref')] for item in opf.xpath('//*[local-name()="spine"]/*[local-name()="itemref"]') if item.get('idref') in idmap]
        ordered += [p for p in idmap.values() if p not in ordered]
        return [p for p in ordered if p in names]
    except Exception as e:
        raise BookError('לא ניתן לקרוא את סדר הפרקים מתוך קובץ ה־EPUB.') from e


def extract_nodes(data: bytes):
    validate_book(data)
    nodes: list[Node] = []
    trees = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        paths = _content_paths(z)
        for path in paths:
            raw = z.read(path)
            try:
                tree = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, no_network=True, recover=False, huge_tree=False))
            except etree.XMLSyntaxError as e:
                raise BookError(f'שגיאת XHTML בפרק {path}: {e}') from e
            trees[path] = tree
            bodies = tree.xpath('//*[local-name()="body"]')
            if not bodies:
                continue
            counter = 0
            for elem in bodies[0].iter():
                if not isinstance(elem.tag, str):
                    continue
                tag = _local(elem.tag)
                # .tail is *outside* the current tag; it may belong to a valid paragraph
                if tag not in SKIP_ELEMENTS and not any(_local(a.tag) in SKIP_ELEMENTS for a in elem.iterancestors()):
                    if _eligible(elem.text):
                        nodes.append(Node(f'{path}#{counter}', elem.text, path, path.split('/')[-1], elem, 'text'))
                        counter += 1
                if _eligible(elem.tail) and not any(_local(a.tag) in SKIP_ELEMENTS for a in elem.iterancestors()):
                    nodes.append(Node(f'{path}#{counter}', elem.tail, path, path.split('/')[-1], elem, 'tail'))
                    counter += 1
    return nodes, trees


def chunks(nodes: list[Node], done: dict, max_chars=2400, max_items=16):
    group, count = [], 0
    for n in nodes:
        if n.key in done:
            continue
        size = len(n.original)
        if group and (count + size > max_chars or len(group) >= max_items):
            yield group
            group, count = [], 0
        group.append(n)
        count += size
    if group:
        yield group


def _validate_output(group: list[Node], results: list[str]):
    if len(group) != len(results):
        raise ValueError('המודל החזיר מספר קטעים שונה מהנדרש.')
    for n, t in zip(group, results):
        if not isinstance(t, str) or not t.strip():
            raise ValueError('המודל החזיר קטע ריק.')
        if len(LATIN_WORDS.findall(n.original)) >= 7 and len(n.original.strip()) >= 45 and not HEBREW.search(t):
            raise ValueError('נמצא קטע ארוך שלא תורגם לעברית.')
    return results


def gemini_translate(client, model: str, group: list[Node], glossary: str, context: str = '') -> list[str]:
    from google.genai import types
    strings = [n.original for n in group]
    instruction = ("You are an expert literary translator from English to Hebrew. Translate faithfully, fluently, "
                   "and completely, without shortening, paraphrasing away details, censorship, added passages, "
                   "or commentary. Preserve proper names consistently, punctuation, narrative voice, dialogue, "
                   "speaker identity and paragraph meaning. Output natural Hebrew, not English. "
                   "Return a JSON object with exactly one property 'translations': an array of strings, "
                   "one translation corresponding to each input string in the exact same order. "
                   "Input strings may represent adjacent fragments of a sentence due to book styling; "
                   "respect the continuity. Do not merge or split array elements. "
                   "Do not translate URLs or formatting codes.")
    prompt = json.dumps({'glossary': glossary[:4000], 'preceding_context': context[-1000:], 'source_segments': strings}, ensure_ascii=False)
    last = None
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=instruction,
                    response_mime_type='application/json',
                    response_schema={'type':'OBJECT','properties':{'translations':{'type':'ARRAY','items':{'type':'STRING'}}},'required':['translations']},
                    temperature=0.2,
                    max_output_tokens=8192,
                ),
            )
            obj = json.loads(response.text)
            return _validate_output(group, obj['translations'])
        except Exception as e:
            last = e
            msg = str(e).lower()
            if any(s in msg for s in ('429', 'resource_exhausted', 'quota', 'rate limit')):
                raise QuotaStop('מכסת הבקשות הסתיימה או הגעת להגבלת קצב. שמור נקודת חידוש ונסה שוב לאחר איפוס המכסה.') from e
            if any(s in msg for s in ('401', '403', 'api key', 'permission_denied', 'billing')):
                raise BookError('המפתח אינו תקין או שלמודל אין הרשאה בפרויקט הזה. בדוק את Google AI Studio.') from e
            if attempt == 0:
                time.sleep(1)
    raise BookError(f'לא ניתן להשלים מקטע לאחר שני ניסיונות: {str(last)[:250]}')


def make_epub(original: bytes, translations: dict[str,str]) -> bytes:
    nodes, trees = extract_nodes(original)
    for n in nodes:
        t = translations.get(n.key)
        if t is None:
            continue
        # preserve original whitespace around all text nodes, including inline formatting
        prefix = n.original[:len(n.original) - len(n.original.lstrip())]
        suffix = n.original[len(n.original.rstrip()):]
        setattr(n.element, n.attr, prefix + t.strip() + suffix)
    replacements = {}
    for path, tree in trees.items():
        bodies = tree.xpath('//*[local-name()="body"]')
        if bodies:
            bodies[0].set('dir', 'rtl')
            bodies[0].set('{http://www.w3.org/XML/1998/namespace}lang', 'he')
        replacements[path] = etree.tostring(tree, encoding='utf-8', xml_declaration=True)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as src, zipfile.ZipFile(out, 'w') as dst:
        for info in src.infolist():
            contents = replacements.get(info.filename)
            if contents is None:
                contents = src.read(info.filename)
            dst.writestr(info, contents)
    return out.getvalue()


def save_checkpoint(original: bytes, translations: dict, model: str, glossary: str) -> bytes:
    """Portable snapshot: source EPUB and validated translated segments, no keys."""
    out = io.BytesIO()
    payload = {'format_version': 1, 'sha256': hashlib.sha256(original).hexdigest(),
               'model': model, 'glossary': glossary, 'translations': translations}
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('source.epub', original)
        z.writestr('progress.json', json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    return out.getvalue()


def load_checkpoint(archive: bytes):
    if len(archive) > 90 * 1024 * 1024:
        raise BookError('קובץ החידוש גדול מדי.')
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            if set(z.namelist()) != {'source.epub', 'progress.json'}:
                raise BookError('זה אינו קובץ חידוש של האפליקציה.')
            original = z.read('source.epub')
            meta = json.loads(z.read('progress.json'))
        validate_book(original)
        if meta.get('format_version') != 1 or hashlib.sha256(original).hexdigest() != meta['sha256']:
            raise BookError('קובץ החידוש אינו תקין.')
        nodes, _ = extract_nodes(original)
        valid_keys = {n.key for n in nodes}
        trans = meta['translations']
        if not isinstance(trans, dict) or any(k not in valid_keys or not isinstance(v, str) for k,v in trans.items()):
            raise BookError('מידע התרגום בקובץ החידוש אינו תקין.')
        return original, trans, meta.get('model','gemini-2.5-flash'), meta.get('glossary','')
    except (KeyError, ValueError, zipfile.BadZipFile, UnicodeDecodeError) as e:
        raise BookError('לא ניתן לקרוא את קובץ החידוש.') from e
