# NassBraille (نص برايل)

A Windows app that converts study notes (PDF or Word) into a **Word** file and a **TXT** file containing only the printed text, in the original reading order and without images, so they can be read on a braille device such as the HumanWare BrailleOne. The app works **fully offline**.

## Usage
1. Open `NassBraille.exe`.
2. Click «اختار ملف» (Choose file), or drag the file onto the app.
3. The review screen shows an image of each page next to the text extracted from it:
   - Uncertain spots are highlighted.
   - F8 jumps to the next issue.
   - «اتراجعت ✓» (Reviewed) marks the page as reviewed.
4. «حفظ الملفات» (Save files): pick a USB drive from the list, or any folder.

Review progress is saved automatically to `<file name>.nassbraille.json` next to the original, so you can close the app and pick up where you left off.

## Expected accuracy

| File type | Result |
|---|---|
| Word (docx/doc) | Exact text |
| PDF exported from Word or another word processor | Nearly all text correct (measured 100% on the reference file) |
| PDF with legacy Arabic fonts (Sultan, AGA, etc.) | About 97–98% of the text; the rest is mostly text inside images |
| Covers and images containing text, or scanned PDFs | Can't be extracted offline; the report flags them |

## For developers
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest tests -q                  # tests
.venv\Scripts\python -m nassbraille.eval <file.pdf> <gold_dir>   # measure accuracy against a reviewed copy
.venv\Scripts\python -m nassbraille.cli <files...> -o <out>     # command-line conversion
.venv\Scripts\python app.py                              # GUI
powershell -ExecutionPolicy Bypass -File build.ps1       # build dist\NassBraille
```

### How the PDF engine works (`nassbraille/pdf/`)
- **`device.py`**: records what MuPDF draws on the page: glyphs and their fonts, images, clips, each item's position in the document structure (struct tree), and /ActualText.
- **`fonts.py`, `legacy.py` and `decide.py`**: every font has two readings: its ToUnicode map, and a reading from the font itself (cmap, glyph names, GSUB, and a table of legacy Arabic fonts). For each font, the app picks the reading that yields valid Arabic.
- **`lines.py`**: builds lines from glyph positions: right-to-left ordering, restoring the order of digits and Latin text, spacing, and mirroring brackets.
- **`tagged.py`**: if the file is tagged, reading order follows the structure tree, and frames and tables are handled separately. It also picks up the hidden text Word adds for lines it converted to images.
- **`geometric.py`**: for untagged files: columns, paragraphs, frames from drawn rectangles, and header/footer removal.
- **`headings.py`**: detects headings from font styling when they have no heading tag.

The reference files in `tests/fixtures/` are local only and must not be distributed.
