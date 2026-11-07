# EPUB Hebrew Translator — RTL + automatic full-book translation

## What's new
- Hebrew RTL user interface (including labels, inputs, upload controls and progress).
- One click translates all remaining text segments sequentially, without a per-batch slider.
- Automatically saves a local checkpoint after every successful group, and makes a portable ZIP checkpoint available for download.
- Full Hebrew EPUB is available when all segments are complete.
- Selectable delay between requests, default 10 seconds; the free Gemini API may still reach rate/day quotas.

## Update existing Streamlit app
1. Unzip this archive locally.
2. Upload `app.py`, `translator.py`, `requirements.txt`, and `README.md` to the **root** of the same GitHub repository and branch already deployed.
3. Commit changes; Streamlit Community Cloud updates the app automatically. If it stays on the old version, refresh or reboot the app from its Streamlit dashboard.
4. Open the same `.streamlit.app` address, supply a Gemini API key from https://aistudio.google.com/apikey (verify the project is Free), and upload your non-DRM EPUB.
5. Click **התחל / המשך תרגום הספר כולו**. Leave the browser tab open. Download your checkpoint ZIP if stopped or limited; on a later session upload that ZIP to resume. When done download the full EPUB.

## Limitations you should know
- This is an **interactive** Streamlit app, not a persistent/background job scheduler. Browser disconnections, server restarts, or hitting quotas can interrupt translation. A local on-server checkpoint is automatic but **not durable** across cloud server restarts. The ZIP you download is the portable backup.
- Rate limits vary per project and model. A full book might take multiple sessions/days, even with one-click translation.
- Google AI subscription and Google Gemini API are billed/limited separately; do not enable billing for a Free-only project. Google may use Free tier content to improve products.
- Some EPUB content (such as embedded images with English text) is not translated. HTML text nodes are translated while formatting and images are preserved; footnotes/navigation and complex inline typography need QA. EPUB metadata/title may retain original language.
- The source book must be free of DRM, and you must have the rights/authorization to translate it.

## Technical
Python 3.10+, Streamlit, `google-genai`, `lxml`. App entry point: `app.py`. The API key is not written to checkpoint files or local disk.
