# Accord — Agreement Metadata Extraction

An AI system that reads an uploaded agreement (scanned image, PDF, `.docx`, and more) and extracts six metadata fields **without regex or rule-based parsing**:

| Field | Format |
|---|---|
| Agreement Value | numeric string (no currency or separators) |
| Agreement Start Date | `DD.MM.YYYY` |
| Agreement End Date | `DD.MM.YYYY` |
| Renewal Notice (Days) | numeric string |
| Party One | text |
| Party Two | text |

Each field comes back with a **status** (`found`, `inferred`, `uncertain`, `missing`), a short **evidence quote** from the source, and an **explanation**, so a human can review it quickly.

The project provides three ways to use it: a **web UI**, a **REST API**, and a **batch CLI** for predictions and evaluation.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Web framework | FastAPI, served by Uvicorn |
| Data validation | Pydantic v2 |
| LLM access | `openai` SDK (used for both OpenAI and Groq via its OpenAI-compatible endpoint) |
| Models | OpenAI `gpt-4.1-mini` (default) or Groq `qwen/qwen3.8-27b` (both configurable) |
| Document reading | `pypdfium2` (PDF), `python-docx` (DOCX), `openpyxl` (XLSX), `python-pptx` (PPTX), `Pillow` (images), `BeautifulSoup4` (HTML), `striprtf` (RTF), `defusedxml` (safe XML) |
| Config | `python-dotenv` |
| Frontend | Plain HTML, CSS and JavaScript (no framework or build step) |
| Testing | `pytest`, `httpx`, and Playwright (browser smoke test) |

---

## How It Works

```text
Browser upload → FastAPI → format reader → text + image sections
                                           ↓
                        OpenAI Responses API / Groq Chat Completions
                                           ↓
                        validation → 6 fields + evidence + notes
                                           ↓
                           UI / REST API / CLI → evaluation
```

1. **Upload.** A file arrives through the UI, `POST /api/extract`, or the CLI.
2. **Read.** `readers.py` decodes the file format only; it never picks out agreement values. It produces extracted text plus page images (PDF pages are rendered, and tall images are tiled with a 100 px overlap so text stays legible). Scanned documents are handled by the model's vision, so no separate OCR is installed.
3. **Extract.** `extraction.py` sends the text and images to a pretrained multimodal LLM, zero-shot, with a fixed instruction prompt. The prompt treats document content as untrusted data, distinguishes rent from deposits, commencement from signing date, parties from witnesses, and renewal notice from termination notice.
   - **OpenAI:** structured output parsed straight into the Pydantic schema.
   - **Groq:** JSON mode with the schema in the prompt, plus one retry on validation failure. Documents with more than three image sections are first transcribed in batches of three, then interpreted together.
4. **Validate.** Output is checked against the `Agreement` schema, and impossible dates (such as `31.02.2011`) are cleared and flagged.
5. **Return.** The result contains the six fields, document type, one-line summary, currency, and warnings.

The train and test CSVs are **never read during inference** and are not used for fine-tuning or few-shot examples.

---

## Project Structure

```text
.
├── app/
│   ├── main.py          # FastAPI routes + serves the UI
│   ├── readers.py       # File-format decoding, image tiling, size limits
│   ├── extraction.py    # Prompt, OpenAI/Groq calls, response validation
│   ├── schemas.py       # Pydantic models (Field, Agreement) + CSV column mapping
│   ├── cli.py           # predict / evaluate / audit commands
│   ├── config.py        # Env settings, provider definitions, limits
│   └── static/          # index.html, style.css, app.js
├── tests/               # pytest suites + Playwright browser smoke test
├── data/                # Supplied dataset (train/, test/, train.csv, test.csv)
├── requirements.txt     # Dependency ranges
├── requirements.lock.txt# Verified versions
├── package.json         # Playwright (UI tests only)
├── .env.example         # Environment template
└── assignment-details.pdf
```

---

## Setup

Requires **Python 3.12+**.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.lock.txt
cp .env.example .env
```

Edit `.env`:

```dotenv
AI_PROVIDER=groq                   # or openai
GROQ_API_KEY=your_key_here
GROQ_MODEL=qwen/qwen3.8-27b
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
```

> Never commit `.env`. A Groq key (`gsk_…`) only works with Groq and an OpenAI key (`sk-…`) only with OpenAI; the app rejects mismatches.

---

## Usage

### 1. Web UI

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>.

1. Drop in one or more documents (up to 20).
2. Check the **Source document** tab to see what was read.
3. Click **Extract details**. A key can come from `.env` or be entered under **Connect AI**; a key entered in the UI lives only in page memory.
4. Review values, evidence and warnings, then export as CSV (all) or JSON (one).

Previewing files works without any API key.

### 2. REST API

Interactive docs: <http://127.0.0.1:8000/docs>

| Endpoint | Purpose |
|---|---|
| `GET /api/config` | Supported formats, limits, providers, whether a server key is configured |
| `POST /api/preview` | Multipart `file` → decoded text and image sections |
| `POST /api/extract` | Multipart `file`, optional `provider` (`groq`/`openai`) and `model`; optional `X-API-Key` header |

```bash
curl -X POST http://127.0.0.1:8000/api/extract \
  -F 'file=@data/test/24158401-Rental-Agreement.png' \
  -F 'provider=groq' \
  -F 'model=qwen/qwen3.8-27b'
```

Response shape:

```json
{
  "filename": "...",
  "provider": "groq",
  "model": "...",
  "result": {
    "document_type": "Rental agreement",
    "summary": "...",
    "currency": "INR",
    "agreement_value": {"value": "12000", "status": "found", "evidence": "...", "explanation": "..."},
    "agreement_start_date": {"...": "..."},
    "agreement_end_date": {"...": "..."},
    "renewal_notice_days": {"...": "..."},
    "party_one": {"...": "..."},
    "party_two": {"...": "..."},
    "warnings": []
  }
}
```

### 3. CLI: batch predictions and evaluation

```bash
# Generate predictions for every document in a folder
python -m app.cli predict data/test --provider groq --output output/test_predictions.csv

# Per-field exact-match recall against labels
python -m app.cli evaluate --predictions output/test_predictions.csv \
                           --labels data/test.csv --output output/metrics.json

# Read-only audit of dataset inconsistencies
python -m app.cli audit
```

`predict` writes the assignment-format CSV plus a companion JSON with evidence, model, warnings and any failures. Failed files keep an empty row and cause a non-zero exit code.

**Metric:** `recall = exact matches / non-blank ground-truth values` per field. Missing predictions count as failures, and blank labels are excluded. A whitespace-trimmed score is reported separately as a supplementary number.

---

## Supported Formats and Limits

| Type | Extensions |
|---|---|
| Documents | `.pdf`, `.docx`, `.odt`, `.rtf` |
| Images | `.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`, `.bmp`, `.gif` |
| Text / data | `.txt`, `.md`, `.csv`, `.tsv`, `.json`, `.html`, `.htm`, `.xml`, `.eml` |
| Office | `.xlsx`, `.pptx` |

Per file: **20 MB**, **30** pages/frames/slides, **40** image sections, **120,000** text characters. Legacy `.doc`/`.xls`/`.ppt`, password-protected files, HEIC, archives, audio and video are not supported. Export them to PDF or a modern format first.

---

## Tests

```bash
python -m pytest -q
```

The 31 tests cover readers, the API, evaluation logic, dataset auditing, and Groq-specific behaviour (image batching, JSON retries, truncation, provider/key mismatches). Provider calls are mocked, so no API key or spending is needed. `tests/conftest.py` blanks credentials so tests can never use real keys.

Optional browser test:

```bash
npm install
npx playwright install chromium
npm run test:ui
```

---

## Known Dataset Issues

- `24158401-Rental-Agreement` is labelled in both `train.csv` and `test.csv`, but its file exists only in `test/`.
- `46239065-Standard-Rental-Agreement-Rental-With-Performance-Fee.docx` has no training label.
- Three training end dates are impossible calendar dates (`31.11.2009`, `31.04.2011`, `31.02.2011`).
- One notice label is blank, and several names and dates have stray whitespace.

These can lower exact-match scores even when an extraction is faithful to the source. The original data is left unmodified.

---

## Results

Per-field recall (exact match; a missing value counts as a miss). Predictions: `predictions/test_predictions.csv`.

| Field | Test (4 docs) | Train (7 docs) |
|---|---|---|
| Agreement Value | 1.00 | 0.86 |
| Agreement Start Date | 1.00 | 0.71 |
| Agreement End Date | 0.75 | 0.71 |
| Renewal Notice (Days) | 1.00 | 0.86 |
| Party One | 1.00 | 0.71 |
| Party Two | 0.75 | 0.71 |

**How these numbers were produced**
- **Test:** complete runs, no failed documents. One run on `openai/gpt-oss-120b` and a later run of the final prompt on
  `openai/gpt-oss-20b` (all 4 documents, recorded in `predictions/test_run_info.txt`) gave identical scores.
- **Train:** from the last complete run on `openai/gpt-oss-120b`. The train set excludes the 3 documents used as few-shot
  examples (`18325926`, `47854715`, `50070534`). That run predates two small prompt edits (a comma before Jr./Sr., and a clearer
  rule to drop the "S/o ..." part of a name). After the Jr./Sr. edit, Party One reached 0.71 on train in a run where 3 of the 7
  documents were handled by the smaller fallback model, because the daily quota ran out. A full train rerun with the final prompt on
  the main model is the one open item.
- **Run-to-run variation:** language models are not perfectly repeatable. In one run of the same code, test Party Two dropped to
  0.50 because the model kept "S/O Charnel Singh" in a name. With 4 test documents, one miss moves a field by 25 points.

### Adjusted recall (excluding label/source issues)

Some labels cannot be reproduced from the file provided (garbled source text, impossible dates, labels that contradict the
document). `data/known_label_issues.csv` lists each such cell with its reason. Recall on the remaining cells:

| Field | Test |
|---|---|
| Agreement Value | 4/4 = 1.00 |
| Agreement Start Date | 4/4 = 1.00 |
| Agreement End Date | 3/3 = 1.00 (1 excluded) |
| Renewal Notice (Days) | 4/4 = 1.00 |
| Party One | 4/4 = 1.00 |
| Party Two | 3/3 = 1.00 (1 excluded) |

---

## Limitations and Security Notes

- Built for single-user local use on `127.0.0.1`. There is no authentication, rate limiting, HTTPS or job queue; add these before exposing it to a network.
- Document content is sent to the selected provider (OpenAI requests set `store=False`; each provider's retention policy still applies).
- Evidence quotes and explanations are model-generated review aids, not verified citations or calibrated confidence scores. Always review results before relying on them.
- Poor handwriting, blur, rotation or very small text can reduce accuracy.
