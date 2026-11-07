import io
import json
import zipfile
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import translator as t


def epub(long=False):
    sentence = 'The room was quiet and the sun was rising slowly over the mountains. '
    words = sentence * (40 if long else 2)
    files={
     'mimetype':b'application/epub+zip',
     'META-INF/container.xml':b'''<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''',
     'OEBPS/content.opf':b'''<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:language>en</dc:language></metadata><manifest><item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>''',
     'OEBPS/chapter.xhtml':('<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Hello <em>dear</em> friend. '+words+'</p><pre>Never change this code</pre><p>Other paragraph.</p></body></html>').encode(),
     'OEBPS/image.png':b'FAKEIMAGE',
    }
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:
        z.writestr('mimetype',files.pop('mimetype'),compress_type=zipfile.ZIP_STORED)
        for k,v in files.items():z.writestr(k,v)
    return output.getvalue()


def test_roundtrip_epub_and_checkpoint():
    source=epub()
    nodes, trees, opf=t.parse_book(source)
    assert nodes
    assert all('Never change this code' not in s.source for s in nodes)
    done={s.key:'שלום עולם ספר זה תורגם היטב' for s in nodes}
    checkpoint=t.save_checkpoint(source,done,'gemini-2.5-flash','Michael=מייקל')
    orig, loaded, model, glossary=t.load_checkpoint(checkpoint)
    assert orig==source and loaded==done and glossary
    out=t.make_epub(orig,loaded)
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        assert z.infolist()[0].filename=='mimetype'
        assert z.infolist()[0].compress_type==zipfile.ZIP_STORED
        x=z.read('OEBPS/chapter.xhtml').decode()
        assert 'dir="rtl"' in x and 'Never change this code' in x
        assert 'שלום' in x and 'Other paragraph.' not in x
        assert '<dc:language>he</dc:language>' in z.read('OEBPS/content.opf').decode()
        assert z.read('OEBPS/image.png')==b'FAKEIMAGE'


def test_long_split_reversible_and_epub_complete():
    src=epub(long=True)
    nodes,_,_=t.parse_book(src)
    assert all(len(s.source)<=t.MAX_SEGMENT_CHARS for s in nodes)
    assert any(s.part>0 for s in nodes)
    grouping={}
    for n in nodes:grouping.setdefault(n.parent_key,[]).append(n.source)
    assert any(len(a)>1 for a in grouping.values())
    done={s.key:'שלום לכל העולם המיוחד' for s in nodes}
    assert t.make_epub(src,done)
    with pytest.raises(t.BookError):t.make_epub(src,{})


def test_corrupt_checkpoint():
    source=epub()
    nodes,_,_=t.parse_book(source)
    cp=t.save_checkpoint(source,{nodes[0].key:'שלום'},'gemini-2.5-flash','')
    with zipfile.ZipFile(io.BytesIO(cp)) as z:
        body=json.loads(z.read('progress.json'))
    body['sha256']='0'*64
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('source.epub',source)
        z.writestr('progress.json',json.dumps(body))
    with pytest.raises(t.BookError):t.load_checkpoint(b.getvalue())


def test_duplicate_zip_entries_rejected():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('mimetype',b'application/epub+zip')
        z.writestr('mimetype',b'application/epub+zip')
    with pytest.raises(t.BookError):t.validate_epub(b.getvalue())

class ApiEx(Exception):
    def __init__(self,code,details=None):
        super().__init__('error')
        self.code=code
        self.details={'details':details or []}


def test_429_classification():
    daily=ApiEx(429,[{'@type':'type.googleapis.com/google.rpc.QuotaFailure','violations':[{'quotaId':'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}])
    rpm=ApiEx(429,[{'@type':'type.googleapis.com/google.rpc.QuotaFailure','violations':[{'quotaId':'GenerateRequestsPerMinutePerProjectPerModel'}]},{'@type':'type.googleapis.com/google.rpc.RetryInfo','retryDelay':'14s'}])
    unknown=ApiEx(429)
    assert t.classify_error(daily)[0]=='daily'
    assert t.classify_error(rpm)==('temporary_quota',14.0)
    assert t.classify_error(unknown)[0]=='unknown_quota'
    assert t.classify_error(ApiEx(400))[0]=='invalid'
    assert t.classify_error(ApiEx(503))[0]=='temporary'


def test_stop_on_daily_without_retries(monkeypatch):
    src=epub(); segs,_,_=t.parse_book(src)
    calls=[]
    def fake(*args): calls.append(1);raise ApiEx(429,[{'@type':'google.rpc.QuotaFailure','violations':[{'quotaId':'RPD'}]}])
    monkeypatch.setattr(t,'_call_model',fake)
    with pytest.raises(t.StopTranslation) as ex:
        t.translate_group(object(),'model',segs[:1],sleep=lambda _:None)
    assert ex.value.kind=='daily' and len(calls)==1


def test_transient_retry_bounded(monkeypatch):
    src=epub(); segs,_,_=t.parse_book(src)
    calls=[]; sleep=[]
    def fake(*args): calls.append(1);raise ApiEx(503)
    monkeypatch.setattr(t,'_call_model',fake)
    with pytest.raises(t.StopTranslation) as ex:
        t.translate_group(object(),'model',segs[:1],sleep=sleep.append)
    assert ex.value.kind=='temporary' and len(calls)==3 and len(sleep)==2


def test_partial_split_callback_preserves_first_half(monkeypatch):
    src=epub(); segs,_,_=t.parse_book(src)
    group=segs[:2]
    cache={}
    def fake(_,__,chosen,___,____):
        if len(chosen)>1:raise t.BookError('bad output')
        if chosen[0].key==group[1].key:raise ApiEx(429)
        return ['שלום כאן']
    monkeypatch.setattr(t,'_call_model',fake)
    with pytest.raises(t.StopTranslation):
        t.translate_group(object(),'model',group,on_partial=lambda gs,ts:cache.update({a.key:b for a,b in zip(gs,ts)}),sleep=lambda _:None)
    assert group[0].key in cache and group[1].key not in cache

def test_error_payload_nested_and_permission():
    ex=ApiEx(429)
    ex.details={'error':{'code':429,'status':'RESOURCE_EXHAUSTED','details':[{
       '@type':'type.googleapis.com/google.rpc.QuotaFailure',
       'violations':[{'quotaMetric':'generativelanguage.googleapis.com/generate_content_free_tier_requests_per_day'}]
    }]}}
    assert t.classify_error(ex)[0]=='daily'
    assert t.classify_error(ApiEx(403))[0]=='auth'
    assert t.classify_error(ApiEx(404))[0]=='model'


def test_pacer_applies_to_recursive_split(monkeypatch):
    src=epub(); segs,_,_=t.parse_book(src)
    group=segs[:3]
    calls=[]; paced=[]
    def fake(client,model,g,glossary,context):
        calls.append(len(g))
        if len(g)>1: raise t.BookError('invalid length')
        return ['שלום']
    monkeypatch.setattr(t,'_call_model',fake)
    done={}
    result=t.translate_group(object(),'model',group,pacer=lambda:paced.append(1),
       on_partial=lambda gs,ts:done.update({s.key:x for s,x in zip(gs,ts)}),sleep=lambda _:None)
    assert len(result)==len(group)==len(done)
    assert len(calls)==len(paced)


def test_output_invalid_counts_and_ratio():
    src=epub(long=True); segs,_,_=t.parse_book(src)
    with pytest.raises(t.BookError):t.validate_translations(segs[:2],['שלום'])
    with pytest.raises(t.BookError):t.validate_translations(segs[:1],[''])
    long=next(s for s in segs if len(s.source)>180)
    with pytest.raises(t.BookError):t.validate_translations([long],['אב'])
