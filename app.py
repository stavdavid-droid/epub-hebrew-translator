import hashlib
import io
import re
import streamlit as st
from translator import (BookError, QuotaStop, chunks, extract_nodes, gemini_translate,
                        load_checkpoint, make_epub, save_checkpoint)

st.set_page_config(page_title='מתרגם ספרי EPUB לעברית', page_icon='📖', layout='centered')
st.title('מתרגם ספרי EPUB לעברית')
st.caption('Gemini API · תרגום נאמן למקור · שמירת התקדמות · EPUB בכיווניות עברית')
st.info('האפליקציה משתמשת ב־Gemini API. שימוש חינמי אפשרי רק במסגרת המכסה החינמית של פרויקט Google AI Studio, ולא מכוח מנוי Gemini לאתר.')
if st.session_state.get('last_message'):
    st.info(st.session_state.pop('last_message'))

if 'book' not in st.session_state:
    st.session_state.book = None
    st.session_state.done = {}
    st.session_state.filename = 'book.epub'
    st.session_state.model = 'gemini-2.5-flash'
    st.session_state.glossary = ''

with st.expander('מה צריך כדי להתחיל?', expanded=st.session_state.book is None):
    st.markdown('1. צור מפתח חינמי באתר [Google AI Studio](https://aistudio.google.com/apikey).\n'
                '2. אל תפעיל Billing אם ברצונך להישאר במסלול החינמי.\n'
                '3. העלה ספר EPUB ללא DRM או קובץ חידוש ZIP.\n'
                '4. אחרי כל סבב תרגום הורד קובץ חידוש. בפעם הבאה העלה אותו כדי להמשיך.\n'
                '5. בסיום הורד EPUB מלא בעברית.')

api_key = st.text_input('Gemini API key', type='password', help='המפתח נשמר בזיכרון הטופס לצורך שימוש זמני ואינו נכתב לקובץ החידוש.')
model = st.selectbox('מודל תרגום', ['gemini-2.5-flash', 'gemini-2.5-flash-lite'],
                     index=0 if st.session_state.model == 'gemini-2.5-flash' else 1,
                     help='Flash הוא ברירת המחדל לאיכות; Flash-Lite עשוי להיות מהיר וחסכוני יותר במכסה.')
source = st.file_uploader('העלה EPUB מקורי או קובץ חידוש ZIP', type=['epub', 'zip'])
if source:
    stamp = hashlib.sha256(source.getvalue()).hexdigest()
    if st.session_state.get('uploaded_stamp') != stamp:
        try:
            if source.name.lower().endswith('.zip'):
                book, done, saved_model, glossary = load_checkpoint(source.getvalue())
                st.session_state.model = saved_model
                st.session_state.glossary = glossary
                st.session_state.filename = 'translated_book.epub'
            else:
                book = source.getvalue()
                extract_nodes(book)  # validate immediately
                done = {}
                st.session_state.filename = source.name
                st.session_state.glossary = ''
            st.session_state.book = book
            st.session_state.done = done
            st.session_state.uploaded_stamp = stamp
            st.success('הספר נטען בהצלחה.')
        except BookError as e:
            st.error(str(e))

if st.session_state.book:
    try:
        nodes, _ = extract_nodes(st.session_state.book)
        done = st.session_state.done
        total = len(nodes)
        finished = sum(n.key in done for n in nodes)
        st.subheader('התקדמות התרגום')
        st.progress(finished / max(total, 1), text=f'{finished:,} מתוך {total:,} מקטעי טקסט')
        st.caption('מספר המקטעים אינו מספר הפרקים. התרגום שומר על מבנה הקבצים בפרקים המקוריים.')
        glossary = st.text_area('מילון שמות ומונחים (אופציונלי)', value=st.session_state.glossary,
                                help='לדוגמה: John → ג׳ון. להקפיד על איות עקבי לאורך הספר.')
        st.session_state.glossary = glossary
        batches = st.slider('מספר קבוצות לתרגום בכל הפעלה', 1, 25, 5,
                            help='מומלץ להתחיל ב־2 לבדיקת איכות. כל קבוצה כוללת עד 16 מקטעים.')
        st.warning('התקדמות בזיכרון האתר עלולה להימחק כשהשרת מופעל מחדש. הורד קובץ חידוש אחרי כל הפעלה ושמור אותו במחשב. אין המשך אוטומטי בזמן שהאתר סגור.')
        if finished < total and st.button('תרגם את קבוצות הטקסט הבאות', type='primary', disabled=not api_key):
            from google import genai
            client = genai.Client(api_key=api_key)
            groups = chunks(nodes, done)
            bar = st.progress(0, text='מתרגם...')
            translated_groups = 0
            try:
                for g in groups:
                    if translated_groups >= batches:
                        break
                    previous = ''
                    first_index = next((i for i, x in enumerate(nodes) if x.key == g[0].key), 0)
                    prior = [done[x.key] for x in nodes[max(0, first_index-10):first_index] if x.key in done]
                    previous = ' '.join(prior[-5:])
                    result = gemini_translate(client, model, g, glossary, previous)
                    for node, txt in zip(g, result):
                        done[node.key] = txt
                    translated_groups += 1
                    bar.progress(translated_groups / batches, text=f'הושלמו {translated_groups} קבוצות בהפעלה הנוכחית')
                st.session_state.model = model
                st.session_state.last_message = 'התרגום התקדם. הורד כעת קובץ חידוש לפני שתעזוב את האתר.'
            except QuotaStop as e:
                st.session_state.last_message = str(e)
            except Exception as e:
                st.session_state.last_message = f'התרגום נעצר: {str(e)[:300]}. הורד קובץ חידוש.'
            st.rerun()
        if done:
            stem = re.sub(r'[^\w.-]+', '_', st.session_state.filename.rsplit('.',1)[0])[:90]
            snapshot = save_checkpoint(st.session_state.book, done, model, glossary)
            st.download_button('הורד קובץ חידוש (ZIP) — חשוב', data=snapshot,
                               file_name=f'{stem}_checkpoint.zip', mime='application/zip')
        if finished == total and total > 0:
            st.success('כל מקטעי הטקסט זכו לתרגום. מומלץ לעיין בספר ולבצע הגהה לפני הפצה או שימוש משמעותי.')
            output = make_epub(st.session_state.book, done)
            st.download_button('הורד ספר EPUB מתורגם', data=output,
                               file_name='hebrew_' + st.session_state.filename.replace('.zip','.epub'),
                               mime='application/epub+zip', type='primary')
        elif done:
            # A preview, clearly identified as incomplete
            with st.expander('הורדת EPUB חלקי לבדיקת איכות (לא הספר הסופי)'):
                preview = make_epub(st.session_state.book, done)
                st.download_button('הורד EPUB חלקי', data=preview,
                                   file_name='preview_partial.epub', mime='application/epub+zip')
        if st.button('נקה ספר והתחל מחדש'):
            for k in ('book','done','uploaded_stamp','filename','model','glossary'):
                st.session_state.pop(k, None)
            st.rerun()
    except BookError as e:
        st.error(str(e))
st.divider()
st.caption('הנתונים נשלחים ל־Google Gemini API לצורך תרגום. במסלול החינמי Google עשויה להשתמש בתוכן לשיפור שירותיה. השתמש רק בספרים שיש לך הרשאה לעבד, ואל תשתף מפתחות API.')
