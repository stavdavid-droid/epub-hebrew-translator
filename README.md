# EPUB Hebrew Translator — Gemini free-tier edition

This Streamlit app translates unencrypted EPUB books from English to Hebrew while retaining the EPUB's XHTML, chapters, images, and inline structure. Uses Gemini API (a separate quota from Gemini consumer subscriptions).

## Deploy updates to existing Streamlit app

1. Keep existing GitHub repository / branch / entrypoint `app.py` unchanged.
2. Replace `app.py` and `requirements.txt` in repository root; add/replace `translator.py`.
3. Commit changes to the branch Streamlit currently deploys. Streamlit Community Cloud rebuilds automatically.
4. Create a key at https://aistudio.google.com/apikey with a free-tier project *without enabling Cloud billing*. Verify current limits at https://aistudio.google.com/usage.
5. Open the unchanged *.streamlit.app URL and paste your API key in the password input field. **Never commit keys to GitHub**.
6. Upload EPUB, choose Gemini 2.5 Flash, translate 1–2 batches for first test and download partial EPUB to inspect.
7. Continue in chunks, downloading the **checkpoint ZIP** after every run. Upload the checkpoint ZIP to resume after a tab/host restart. Store it locally: Streamlit Community Cloud does not provide durable local disk storage.
8. Download the final EPUB once all segments are translated.

## Limitations and important notices

- **No fully automatic overnight/background processing**: free-tier quotas, Community Cloud app restarts, and Streamlit request lifetimes mean manual restarts are required. This app deliberately does not claim otherwise.
- Free-tier quota is per Google project, may vary and change. Rate limit 429 stops cleanly; resume later with a checkpoint.
- **Gemini subscription** (consumer app) is *not* Gemini API billing or quota.
- No API key is included in checkpoint archive or source control. However, Google receives book text. Free-tier data may be used for product improvement.
- Each source text node is translated in a contextual batch, retaining original inline tags. For books with aggressive inline styling (sentences split across many tags) quality may be less consistent; review sample chapters. An automated completeness check verifies number of translated text nodes and flags non-Hebrew outputs, but **does not prove semantic fidelity**.
- XHTML parsing requires valid XML; malformed EPUB files are rejected, not auto-repaired. Complex layout/CSS, vertical text, footnotes and reading-system behavior need manual validation. Metadata inside OPF is not translated.
- DRM books are not supported. Only use content you have legal permission to process; do not redistribute copyrighted translations without rights.
- App is best suited for private personal use. Keep Streamlit access private if possible.
