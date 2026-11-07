import hashlib
import os
from pathlib import Path
import streamlit as st
from translator import TranslationError, build_items, output_epub

st.set_page_config(page_title="מתרגם ספרי EPUB לעברית", page_icon="📚", layout="centered")
st.markdown("<style>.block-container {direction:rtl} div[data-testid='stFileUploader'] {direction:rtl} </style>", unsafe_allow_html=True)
st.title("מתרגם ספרי EPUB לעברית")
st.write("מעלים ספר EPUB ללא DRM, מתרגמים ושומרים קובץ EPUB חדש. התרגום שומר על סדר הפרקים, הפסקאות והעיצוב הפנימי ככל האפשר.")

uploaded = st.file_uploader("בחר קובץ EPUB", type=["epub"])
api_key = st.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""), help="המפתח נשלח ישירות ל-OpenAI; אינו נכתב לקובץ באפליקציה.")
model = st.selectbox("מודל התרגום", ["gpt-4.1-mini", "gpt-4.1"], index=0, help="gpt-4.1 איכותי יותר בדרך כלל אך יקר יותר. שימוש ב-API כרוך בתשלום נפרד.")
st.caption("התרגום מבוצע באמצעות OpenAI API בתשלום נפרד ממנוי ChatGPT. הספר נשלח ל-API לצורך התרגום. השתמש רק בקבצים שיש לך הרשאה לתרגם.")

if uploaded:
    data = uploaded.getvalue()
    size = len(data) / (1024*1024)
    try:
        _, paths, _ = build_items(data)
        st.write(f"**קובץ:** {uploaded.name} | **גודל:** {size:.2f} MB | **קובצי פרקים:** {len(paths)}")
    except Exception as exc:
        st.error(str(exc))

if uploaded and api_key and st.button("תרגם את הספר", type="primary"):
    data = uploaded.getvalue()
    progress = st.progress(0)
    status = st.empty()
    def on_progress(done, total, path):
        progress.progress(done / total)
        status.write(f"תורגמו {done} מתוך {total} מקטעים | {path}")
    try:
        output, stats = output_epub(data, model, api_key, Path.home()/".epub_hebrew_translator_cache", on_progress)
        st.session_state["output"] = output
        st.session_state["file_id"] = hashlib.sha256(data).hexdigest()
        st.session_state["filename"] = Path(uploaded.name).stem + "_HE.epub"
        st.session_state["stats"] = stats
        st.success(f"התרגום הסתיים: {stats['chapters']} קובצי פרקים, {stats['segments']} מקטעים. {stats['cached_segments']} מקטעים נטענו מתרגום שמור.")
    except Exception as exc:
        st.error(f"התרגום הופסק: {exc}")
        st.info("אפשר ללחוץ שוב על 'תרגם את הספר' עם אותו קובץ ומודל. המקטעים שכבר תורגמו נשמרים במחשב.")

if uploaded and "output" in st.session_state and st.session_state.get("file_id") == hashlib.sha256(uploaded.getvalue()).hexdigest():
    st.download_button("הורד EPUB מתורגם", data=st.session_state["output"], file_name=st.session_state["filename"], mime="application/epub+zip", type="primary")

with st.expander("מידע והגבלות"):
    st.write("התרגום מתבצע בפסקאות, ולכן ייתכנו אי-אחידות בשמות ובסגנון. ניתן לבקר ולהגיה לאחר התרגום. עימוד מורכב, פרקים חריגים במיוחד, הגנת DRM וטקסט שמופיע בתמונות אינם נתמכים. סגירת האפליקציה באמצע תרגום עוצרת אותו, אך אפשר להמשיך בהרצה חוזרת. אם קובץ EPUB נפתח משמאל לימין במכשיר הקריאה, מומלץ לבדוק את הגדרות תצוגת RTL של הקורא.")
