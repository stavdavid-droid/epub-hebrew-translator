"""Hebrew RTL Streamlit EPUB translator, single-run translation and portable checkpoints."""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from tempfile import gettempdir

import streamlit as st
from translator import (BookError, QuotaStop, chunks, extract_nodes,
                        gemini_translate, load_checkpoint, make_epub, save_checkpoint)

st.set_page_config(page_title='מתרגם ספרי EPUB לעברית', page_icon='📖', layout='centered')
st.markdown('''<style>
html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"],
[data-testid="stMain"], .stMainBlockContainer {direction:rtl; text-align:right;}
h1,h2,h3,h4,p,li,label,div[data-testid="stMarkdownContainer"],
[data-testid="stAlert"], [data-testid="stCaptionContainer"] {text-align:right;}
[data-testid="stExpander"] summary {direction:rtl;}
[data-testid="stFileUploader"] {direction:rtl; text-align:right;}
[data-testid="stFileUploaderDropzone"] {direction:rtl; text-align:right;}
[data-testid="stTextInputRootElement"] input,textarea {direction:rtl; text-align:right;}
[data-testid="stTextInputRootElement"] input[type=password] {direction:ltr; text-align:left;}
[data-testid="stSelectbox"] {direction:rtl; text-align:right;}
[data-testid="stProgress"] {direction:rtl;}
button {direction:rtl;}
/* English model IDs and URLs should retain left-to-right character order. */
code,pre {direction:ltr;text-align:left;}
</style>''', unsafe_allow_html=True)

st.title('מתרגם ספרי EPUB לעברית')
st.caption('ממשק עברי · Gemini API · תרגום ספר מלא בלחיצה אחת · חידוש מנקודת עצירה')
st.info('מנוי Gemini אינו כולל בהכרח שימוש ב־API. לשימוש חינמי ודא שהפרויקט ב־Google AI Studio נמצא במסלול Free.')

if 'session_token' not in st.session_state:
    st.session_state.session_token = uuid.uuid4().hex
if 'done' not in st.session_state:
    st.session_state.done = {}
if 'book' not in st.session_state:
    st.session_state.book = None
if 'filename' not in st.session_state:
    st.session_state.filename = 'book.epub'
if 'glossary' not in st.session_state:
    st.session_state.glossary = ''
if 'model' not in st.session_state:
    st.session_state.model = 'gemini-2.5-flash'

# Local disk survives reruns while this server instance remains online, but not
# Community Cloud restarts/redeploys. User-owned ZIP remains the durable backup.
WORKDIR = Path(gettempdir()) / 'epub_hebrew_progress' / st.session_state.session_token
WORKDIR.mkdir(parents=True, exist_ok=True)

def backup_now():
    if st.session_state.book and st.session_state.done:
        raw = save_checkpoint(st.session_state.book, st.session_state.done,
                              st.session_state.model, st.session_state.glossary)
        p = WORKDIR / 'checkpoint.zip'
        temporary = WORKDIR / 'checkpoint.tmp'
        temporary.write_bytes(raw)
        temporary.replace(p)

def restore_disk_if_available():
    path = WORKDIR / 'checkpoint.zip'
    if path.exists() and st.session_state.book:
        try:
            orig, done, _, _ = load_checkpoint(path.read_bytes())
            if hashlib.sha256(orig).digest() == hashlib.sha256(st.session_state.book).digest() and len(done) > len(st.session_state.done):
                st.session_state.done = done
        except (BookError, OSError):
            pass

with st.expander('הוראות שימוש', expanded=st.session_state.book is None):
    st.markdown('''1. צור מפתח ב־[Google AI Studio](https://aistudio.google.com/apikey) ובדוק שהפרויקט מוגדר Free.
2. הכנס את המפתח, בחר מודל והעלה EPUB ללא DRM.
3. לחץ **התחל תרגום של הספר כולו**. התרגום יתקדם מעצמו, ללא לחיצות על קבוצות.
4. **השאר את הלשונית פתוחה** עד סוף התרגום. אם המכסה נגמרת או החיבור נקטע, הורד קובץ חידוש ZIP כשהממשק זמין.
5. בפעם הבאה העלה את קובץ החידוש והמשך בלחיצה אחת. לאחר השלמה הורד EPUB מלא בעברית.''')

api_key = st.text_input('מפתח Gemini API', type='password', help='המפתח לא נכלל בקובץ החידוש ולא נכתב לדיסק.')
models = ['gemini-2.5-flash', 'gemini-2.5-flash-lite']
model = st.selectbox('מודל התרגום', models, index=models.index(st.session_state.model) if st.session_state.model in models else 0,
                     help='Flash מומלץ לתרגום ספרותי. הזמינות והמכסה החינמית תלויות בפרויקט Google שלך.')
source = st.file_uploader('העלה ספר EPUB או קובץ חידוש ZIP', type=['epub', 'zip'])
if source is not None:
    stamp = hashlib.sha256(source.getvalue()).hexdigest()
    if st.session_state.get('uploaded_stamp') != stamp:
        try:
            if source.name.lower().endswith('.zip'):
                book, done, saved_model, glossary = load_checkpoint(source.getvalue())
                st.session_state.model = saved_model
                st.session_state.glossary = glossary
                filename = 'book_translated.epub'
            else:
                book = source.getvalue()
                extract_nodes(book)
                done, glossary = {}, ''
                filename = source.name
            st.session_state.book = book
            st.session_state.done = done
            st.session_state.filename = filename
            st.session_state.glossary = glossary
            st.session_state.uploaded_stamp = stamp
            backup_now()
            st.success('הקובץ נטען בהצלחה.')
        except BookError as e:
            st.error(str(e))

if st.session_state.book:
    try:
        restore_disk_if_available()
        nodes, _ = extract_nodes(st.session_state.book)
        done = st.session_state.done
        total = len(nodes)
        finished = sum(node.key in done for node in nodes)
        st.subheader('מצב התרגום')
        progress = st.progress(finished/max(total, 1), text=f'{finished:,} מתוך {total:,} מקטעים')
        st.caption('מקטע הוא יחידת טקסט, ולא בהכרח פרק שלם.')
        glossary = st.text_area('מילון שמות ומונחים (לא חובה)', value=st.session_state.glossary,
                                help='לדוגמה: Michael = מייקל. המונחים ישמשו לאורך הספר.')
        st.session_state.glossary = glossary
        request_delay = st.select_slider('השהיה בין בקשות API', options=[2, 5, 10, 15, 30], value=10,
                                         format_func=lambda v: f'{v} שניות', help='השהיה מפחיתה את הסיכון למגבלת בקשות לדקה; לא עוקפת מכסה יומית.')
        st.warning('הפעולה אוטומטית כל עוד ההרצה פועלת והדפדפן מחובר. בסביבת Streamlit החינמית אין הבטחה שהשרת ימשיך לעבוד כשהלשונית נסגרת, או שהנתונים המקומיים יישמרו לאחר אתחול.')
        if finished < total and st.button('התחל / המשך תרגום הספר כולו', type='primary', use_container_width=True, disabled=not bool(api_key)):
            from google import genai
            client = genai.Client(api_key=api_key)
            st.session_state.model = model
            status = st.empty()
            last_error = None
            index_by_key = {node.key: i for i,node in enumerate(nodes)}
            try:
                groups_done = 0
                for group in chunks(nodes, done):
                    prior_index = index_by_key[group[0].key]
                    previous = ' '.join(done[x.key] for x in nodes[max(0, prior_index-10):prior_index] if x.key in done)
                    status.info(f'מתרגם... מקטע {prior_index + 1:,} מתוך {total:,}')
                    translations = gemini_translate(client, model, group, glossary, previous)
                    for node, translated in zip(group, translations):
                        done[node.key] = translated
                    groups_done += 1
                    backup_now()  # automatically saved after every successful group
                    progress.progress(len(done)/max(total,1), text=f'{len(done):,} מתוך {total:,} מקטעים')
                    if len(done) < total:
                        time.sleep(request_delay)
            except QuotaStop as e:
                last_error = f'מגבלת Gemini עצרה את התרגום: {e}. התקדמות התרגום נשמרה בשרת הנוכחי; הורד קובץ חידוש והמשך מאוחר יותר.'
            except (BookError, Exception) as e:
                last_error = f'התרגום נעצר: {str(e)[:300]}. הורד קובץ חידוש לפני עזיבת הדף.'
            finally:
                backup_now()
            status.empty()
            if last_error:
                st.warning(last_error)
            else:
                st.success('תרגום כל המקטעים הושלם! כעת ניתן להוריד EPUB מלא.')
            st.rerun()

        stem = re.sub(r'[^\w.-]+', '_', st.session_state.filename.rsplit('.',1)[0])[:80]
        if done:
            snapshot = save_checkpoint(st.session_state.book, done, model, glossary)
            st.download_button('הורד גיבוי והמשך (ZIP)', data=snapshot,
                               file_name=f'{stem}_checkpoint.zip', mime='application/zip', use_container_width=True)
        if finished == total and total > 0:
            st.success('כל מקטעי המקור הרלוונטיים נשלחו לתרגום. לפני שימוש מומלץ לבצע בדיקת איכות והגהה.')
            output = make_epub(st.session_state.book, done)
            st.download_button('הורד את הספר המלא בעברית (EPUB)', data=output,
                               file_name=f'{stem}_hebrew.epub', mime='application/epub+zip',
                               type='primary', use_container_width=True)
        if st.button('נקה ספר והתחל מחדש'):
            for key in ['book','done','uploaded_stamp','filename','glossary']:
                st.session_state.pop(key, None)
            st.rerun()
    except BookError as e:
        st.error(str(e))

st.divider()
st.caption('קובצי EPUB נשלחים ל־Google Gemini API לשם תרגום. במסלול Free Google עשויה להשתמש בתוכן לשיפור שירותיה. השתמש רק בתוכן שמותר לך לתרגם, ושמור את המפתח בסוד.')
