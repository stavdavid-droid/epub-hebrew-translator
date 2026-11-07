"""Private Streamlit EPUB translator. Deploy with GEMINI_API_KEY and APP_PASSWORD in Secrets."""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import streamlit as st
from translator import (BookError, StopTranslation, load_checkpoint, make_epub,
                        parse_book, pending_groups, save_checkpoint, translate_group)

st.set_page_config(page_title='מתרגם EPUB לעברית', page_icon='📚', layout='centered')
st.markdown('''<style>
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stMainBlockContainer"], [data-testid="stMarkdownContainer"],
[data-testid="stAlert"], [data-testid="stWidgetLabel"], [data-testid="stCaptionContainer"] {
 direction:rtl; text-align:right;
}
[data-testid="stFileUploader"], [data-testid="stFileUploaderDropzone"],
[data-testid="stSelectbox"], [data-testid="stExpander"], [data-testid="stButton"],
[data-testid="stDownloadButton"], [data-testid="stTextArea"] { direction:rtl; text-align:right; }
input,textarea { direction:rtl; text-align:right; }
input[type="password"], code, pre { direction:ltr !important; text-align:left !important; }
button { direction:rtl; }
</style>''', unsafe_allow_html=True)

st.title('מתרגם ספרי EPUB לעברית')
st.caption('תרגום ספר שלם · Gemini · שמירת התקדמות · ממשק עברי')

# Secrets are configured ONCE in Streamlit Cloud Settings → Secrets, never in GitHub.
try:
    API_KEY = str(st.secrets.get('GEMINI_API_KEY','')).strip()
    APP_PASSWORD = str(st.secrets.get('APP_PASSWORD','')).strip()
except Exception:
    API_KEY, APP_PASSWORD = '', ''

if not API_KEY or not APP_PASSWORD:
    st.error('נדרשת הגדרה חד־פעמית של GEMINI_API_KEY ושל APP_PASSWORD במסך Secrets של Streamlit Cloud.')
    st.code('GEMINI_API_KEY = "YOUR_PRIVATE_API_KEY"\nAPP_PASSWORD = "YOUR_STRONG_PRIVATE_PASSWORD"',language='toml')
    st.stop()

if not st.session_state.get('authenticated',False):
    st.subheader('כניסה פרטית')
    st.caption('סיסמת האפליקציה מגנה על מכסת Gemini שלך מפני מבקרים אחרים.')
    with st.form('auth'):
        password = st.text_input('סיסמה',type='password')
        submitted = st.form_submit_button('כניסה', use_container_width=True)
    if submitted:
        if hmac.compare_digest(password,APP_PASSWORD):
            st.session_state.authenticated=True
            st.rerun()
        else:
            st.error('סיסמה לא נכונה.')
    st.stop()

with st.sidebar:
    if st.button('התנתקות'):
        st.session_state.clear()
        st.rerun()

if 'session_id' not in st.session_state:
    st.session_state.session_id = uuid4().hex
if 'done' not in st.session_state: st.session_state.done={}
if 'book' not in st.session_state: st.session_state.book=None
if 'name' not in st.session_state: st.session_state.name='book.epub'
if 'model' not in st.session_state: st.session_state.model='gemini-2.5-flash'
if 'glossary' not in st.session_state: st.session_state.glossary=''

# Fast local working copy only. NOT durable on Streamlit Cloud restart/redeploy.
cache_dir=Path(gettempdir())/'hebrew_epub_jobs'/st.session_state.session_id
cache_dir.mkdir(parents=True,exist_ok=True)
checkpoint_path=cache_dir/'progress.zip'

def snapshot():
    if not st.session_state.book: return
    raw=save_checkpoint(st.session_state.book,st.session_state.done,st.session_state.model,st.session_state.glossary)
    temp=checkpoint_path.with_suffix('.tmp')
    temp.write_bytes(raw)
    temp.replace(checkpoint_path)

def safe_name(name):
    return re.sub(r'[^\w.\-]+','_',Path(name).stem)[:70] or 'book'

with st.expander('הוראות', expanded=st.session_state.book is None):
    st.markdown('''1. העלה ספר EPUB ללא DRM. אם יש לך קובץ חידוש **מהגרסה הזו**, העלה ZIP במקום EPUB.
2. בחר מודל (Flash מומלץ) ולחץ **תרגם את הספר כולו**.
3. השאר את החלון פתוח. התרגום ממשיך אוטומטית, ושומר כל קבוצה שהושלמה.
4. אם יש עצירה, הורד **קובץ חידוש ZIP**. בפעם הבאה העלה אותו והמשך.
5. בסיום הורד את קובץ EPUB המלא. ניתן לשנות את הגדרות Secrets ללא עדכון GitHub.''')

up=st.file_uploader('ספר EPUB או קובץ חידוש ZIP',type=['epub','zip'])
if up is not None:
    raw=up.getvalue()
    fingerprint=hashlib.sha256(raw).hexdigest()
    if fingerprint != st.session_state.get('fingerprint'):
        try:
            if up.name.lower().endswith('.zip'):
                book,done,model,glossary=load_checkpoint(raw)
                name='book.epub'
            else:
                book=raw
                parse_book(book)
                done,model,glossary={},'gemini-2.5-flash',''
                name=up.name
            st.session_state.update(book=book,done=done,model=model,glossary=glossary,
                                    fingerprint=fingerprint,name=name,last_message=None)
            snapshot()
            st.success('הקובץ נטען בהצלחה.')
        except (BookError, OSError) as e:
            st.error(str(e))

if st.session_state.book:
    try:
        book=st.session_state.book
        segments,_,_=parse_book(book)
        if not segments:
            st.warning('לא נמצאו בספר קטעים באנגלית לתרגום.')
            st.stop()
        done=st.session_state.done
        total=len(segments)
        finished=sum(s.key in done for s in segments)
        st.subheader('התקדמות')
        meter=st.progress(finished/total, text=f'{finished:,} מתוך {total:,} מקטעים')
        st.caption('מקטע אינו בהכרח עמוד או פרק. נשמר רק תרגום שעבר בדיקות בסיסיות.')
        st.session_state.model=st.selectbox('מודל תרגום', ['gemini-2.5-flash','gemini-2.5-flash-lite'],
                                          index=['gemini-2.5-flash','gemini-2.5-flash-lite'].index(st.session_state.model))
        st.session_state.glossary=st.text_area('שמות ומונחים לתרגום עקבי (רשות)',value=st.session_state.glossary,
                                              max_chars=3000,height=90)
        delay=st.select_slider('המתנה בין בקשות מוצלחות',options=[5,10,15,20,30],value=10,
                               format_func=lambda x:f'{x} שניות')
        st.info('העבודה רציפה כל עוד הריצה פועלת והחיבור נשמר. היא אינה ממשיכה ברקע לאחר סגירת הדפדפן; אחסון השרת עלול להימחק.')
        if finished < total and st.button('תרגם / המשך את הספר כולו',type='primary',use_container_width=True):
            from google import genai
            from google.genai import types
            # Disable opaque SDK retries: our bounded, classified retry policy owns them.
            client=genai.Client(api_key=API_KEY, http_options=types.HttpOptions(
                timeout=120000, retry_options=types.HttpRetryOptions(attempts=1)))
            message=None
            calls=0
            status=st.empty()
            indices={s.key:i for i,s in enumerate(segments)}
            last_request = [None]
            def pace_request():
                now = time.monotonic()
                if last_request[0] is not None:
                    wait = delay - (now - last_request[0])
                    if wait > 0: time.sleep(wait)
                last_request[0] = time.monotonic()

            def record_partial(subgroup, values):
                for seg, value in zip(subgroup, values):
                    done[seg.key] = value
                snapshot()

            try:
                for group in pending_groups(segments,done):
                    first=indices[group[0].key]
                    preceding=' '.join(done[s.key] for s in segments[max(0,first-8):first] if s.key in done)
                    status.info(f'מתרגם מקטע {first+1:,} מתוך {total:,} ...')
                    translations=translate_group(client,st.session_state.model,group,st.session_state.glossary,preceding,on_partial=record_partial,pacer=pace_request)
                    for s,tr in zip(group,translations): done[s.key]=tr
                    snapshot()  # atomic checkpoint after each successful group
                    calls+=1
                    finished=sum(s.key in done for s in segments)
                    meter.progress(finished/total,text=f'{finished:,} מתוך {total:,} מקטעים')
            except StopTranslation as ex:
                message=f'התרגום נעצר ({ex.kind}): {ex}. הורד קובץ חידוש ZIP כדי לא לאבד את ההתקדמות.'
            except (OSError, BookError) as ex:
                message=f'תקלה בשמירה או בקובץ: {ex}. נסה להוריד את קובץ החידוש.'
            except Exception:
                message='אירעה שגיאה בלתי צפויה. נסה להוריד קובץ חידוש; פרטים טכניים זמינים ביומני השרת.'
            finally:
                try: snapshot()
                except OSError: pass
                try: client.close()
                except Exception: pass
            st.session_state.last_message=message or 'התרגום הושלם.'
            st.rerun()
        if st.session_state.get('last_message'):
            if finished==total: st.success(st.session_state.last_message)
            else: st.warning(st.session_state.last_message)
        if done:
            checkpoint=save_checkpoint(book,done,st.session_state.model,st.session_state.glossary)
            st.download_button('הורד קובץ חידוש ZIP',data=checkpoint,
                               file_name=f'{safe_name(st.session_state.name)}_checkpoint_v4.zip',
                               mime='application/zip',use_container_width=True)
        if finished==total:
            out=make_epub(book,done)
            st.download_button('הורד ספר מתורגם מלא EPUB',data=out,
                               file_name=f'{safe_name(st.session_state.name)}_he.epub',
                               mime='application/epub+zip',type='primary',use_container_width=True)
        if st.button('התחל ספר חדש'):
            for k in ('book','done','fingerprint','name','last_message','glossary'):
                st.session_state.pop(k,None)
            st.rerun()
    except (BookError,OSError) as ex:
        st.error(str(ex))

st.divider()
st.caption('ספרים נשלחים ל־Gemini API. במסלול החינמי Google עשויה להשתמש בתוכן לשיפור השירות. ודא שהפרויקט ב־AI Studio הוא Free; מנוי Gemini אינו מחליף מכסת API.')
