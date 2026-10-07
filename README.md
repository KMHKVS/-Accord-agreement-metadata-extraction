# Accord — Agreement Metadata Extraction

An AI system that reads an uploaded agreement (a scanned image or a `.docx` file) and extracts six metadata fields **without regex or rule-based parsing**:

| Field | Format |
|---|---|
| Agreement Value | numeric string (no currency or separators) |
| Agreement Start Date | `DD.MM.YYYY` |
| Agreement End Date | `DD.MM.YYYY` |
| Renewal Notice (Days) | numeric string |
| Party One | text |
| Party Two | text |

Each field comes back with a **status** (`found`, `inferred`, `uncertain`, `missing`), a short **evidence quote** from the source, and an **explanation**, so a human can review it quickly.

It can be used as a **web UI**, a **REST API**, or a **batch CLI** for predictions and evaluation.

---

## Approach

```text
upload → format reader → text + image sections → multimodal LLM → schema validation → fields + evidence + warnings
```

1. **Read** (`app/readers.py`). The file is decoded to text plus page images. This step converts formats only and never selects values. Tall scans are cut into 2,000 px slices with a 100 px overlap, so small text stays legible. Scanned pages are read by the model's vision input, so no separate OCR engine is used.
2. **Extract** (`app/extraction.py`). A pretrained multimodal LLM receives the text and images with a fixed instruction prompt (zero-shot, no example documents). All field selection is done by the model.
   - **OpenAI:** structured output parsed straight into the Pydantic schema.
   - **Groq:** JSON mode with the schema in the prompt, plus one retry if the response doesn't validate. Documents with more than three image sections are first transcribed in batches of three, then interpreted together.
   - `temperature=0` is set on both providers to make runs more repeatable.
3. **Validate** (`app/schemas.py`). Output must match the `Agreement` schema. If the source itself contains an impossible date (such as `31.02.2011`), the value is kept as written, marked `uncertain`, and a warning is added.
4. **Return** the six fields, document type, one-line summary, currency, and warnings.

**Prompt conventions.** The prompt separates rent from deposits, commencement from signing date, and renewal notice from termination notice (flagged as a fallback). It converts months to days at 30 per month. For names it asks for the party's own name only: no honorifics (Mr, Mrs, Sri, …), no "S/o" style relationship clauses, initials and `Jr.`/`Sr.` suffixes kept. These conventions are only partly supported by the training labels, which are inconsistent (for example `MR.K.Kuttan` keeps its title), so some name mismatches are expected.

The train and test CSVs are **not read during extraction** and no labelled documents appear in the prompt.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Web framework | FastAPI, served by Uvicorn |
| Validation | Pydantic v2 |
| LLM access | `openai` SDK for both OpenAI and Groq (OpenAI-compatible endpoint) |
| Default models | OpenAI `gpt-4.1-mini`; Groq `qwen/qwen3.8-27b` (both configurable). Groq's documentation lists `qwen/qwen3.8-27b` as a vision-capable model, so it can read the scanned images. Any model you substitute must accept images. |
| Readers | `python-docx`, `Pillow`, `pypdfium2`, and others (see secondary formats) |
| Frontend | Plain HTML, CSS and JavaScript |
| Tests | `pytest`, `httpx`, Playwright (browser smoke test) |

---

## Project Structure

```text
.
├── app/
│   ├── main.py          # FastAPI routes, serves the UI
│   ├── readers.py       # File decoding, image slicing, size limits
│   ├── extraction.py    # Prompt, OpenAI/Groq calls, response validation
│   ├── schemas.py       # Pydantic models + CSV column mapping
│   ├── cli.py           # predict / evaluate / audit
│   ├── config.py        # Settings, providers, limits
│   └── static/          # index.html, style.css, app.js
├── tests/               # pytest suites + Playwright smoke test
├── data/                # Supplied dataset (train/, test/, train.csv, test.csv)
├── predictions/         # Prediction CSVs, metrics and run info (see Results)
├── requirements.txt / requirements.lock.txt
├── .env.example
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

Edit `.env` and fill in **one** provider:

```dotenv
AI_PROVIDER=openai                 # or groq
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4.1-mini
GROQ_API_KEY=
GROQ_MODEL=qwen/qwen3.8-27b
```

Never commit `.env`. A Groq key (`gsk_…`) only works with Groq and an OpenAI key (`sk-…`) only with OpenAI; the app rejects mismatches.

---

## Usage

### Web UI

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>, add one or more documents, check the **Source document** tab, then click **Extract details**. Results can be exported as CSV or JSON. Previewing works without an API key.

### REST API

Interactive docs: <http://127.0.0.1:8000/docs>

| Endpoint | Purpose |
|---|---|
| `GET /api/config` | Supported formats, limits, providers |
| `POST /api/preview` | Multipart `file` → decoded text and image sections |
| `POST /api/extract` | Multipart `file`, optional `provider` and `model`; optional `X-API-Key` header |

```bash
curl -X POST http://127.0.0.1:8000/api/extract \
  -F 'file=@data/test/24158401-Rental-Agreement.png' \
  -F 'provider=openai' -F 'model=gpt-4.1-mini'
```

### CLI

```bash
# Predictions for every document in a folder
python -m app.cli predict data/test --provider openai --output predictions/test_predictions.csv

# Per-field recall against labels
python -m app.cli evaluate --predictions predictions/test_predictions.csv \
                           --labels data/test.csv --output predictions/test_metrics.json

# Read-only audit of dataset inconsistencies
python -m app.cli audit
```

`predict` also writes a companion JSON with evidence, model, and warnings. Failed files keep an empty row and make the command exit non-zero.

---

## Evaluation

For each field: `recall = exact matches / non-blank ground-truth values`. A missing prediction counts as a miss and blank labels are excluded. `evaluate` reports two scores:

- **Strict exact match** (the primary score): `prediction == label`, character for character.
- **Whitespace-trimmed match** (supplementary): leading and trailing spaces ignored. This matters because many labels contain stray spaces (for example `"Hanumaiah "`) that a model will never reproduce.

Report both numbers side by side and lead with the strict one.

---

## Results

**Run:** provider Groq, model `qwen/qwen3.8-27b`, code as committed (zero-shot, `temperature=0`). All 4 test documents were processed with 0 failures (`"errors": []` in the prediction JSON). The prediction CSV and the companion JSON (model name, evidence quotes, warnings per field) are in `predictions/`. Date, commit and who ran it are recorded in `predictions/test_run_info.txt`. Scores were recomputed with `python -m app.cli evaluate` against `data/test.csv`.

### Per-field recall (test set, 4 documents)

| Field | Strict exact match | Whitespace-trimmed |
|---|---|---|
| Agreement Value | 4/4 = **1.00** | 1.00 |
| Agreement Start Date | 4/4 = **1.00** | 1.00 |
| Agreement End Date | 4/4 = **1.00** | 1.00 |
| Renewal Notice (Days) | 3/4 = **0.75** | 0.75 |
| Party One | 0/4 = **0.00** | 1.00 |
| Party Two | 1/4 = **0.25** | 0.50 |

Strict exact match is the primary metric. The large gap on the party fields is a labelling artefact: the supplied labels contain stray leading or trailing spaces (for example `"Hanumaiah "`, `" S.Sakunthala"`) that a model does not reproduce. Ignoring only surrounding whitespace, Party One is 4/4. With four documents, one miss moves a field by 25 points, so these figures are indicative rather than statistically meaningful. A second upload of the same run produced identical output.

### Per-document results

`✓` exact match, `≈` equal after trimming whitespace only, `✗` mismatch.

| Document | Value | Start | End | Notice | Party One | Party Two |
|---|---|---|---|---|---|---|
| 24158401 (PNG) | ✓ | ✓ | ✓ | ✓ | ≈ | ≈ |
| 95980236 (PNG) | ✓ | ✓ | ✓ | ✓ | ≈ | ✓ |
| 156155545 (DOCX) | ✓ | ✓ | ✓ | ✓ | ≈ | ✗ |
| 228094620 (DOCX) | ✓ | ✓ | ✓ | ✗ | ≈ | ✗ |

### Error analysis (the real misses)

| Document | Field | Expected | Predicted | Reading |
|---|---|---|---|---|
| 228094620 | Renewal Notice | `30` | *(blank, status `missing`)* | The text allows renewal by mutual consent but states no notice period. The only notice wording is a "one months notice" to vacate for deliberate damage, which the model did not treat as a notice period. The label appears to use that clause as a fallback. |
| 156155545 | Party Two | `VYSHNAVI DAIRY SPECIALITIES Private Ltd` | `SRI VYSHNAVI DAIRY SPECIALITIES Private Ltd.` | The model kept the "SRI" prefix and a trailing full stop that the label omits. The prompt asks for no honorifics, but the model did not apply that to a company name. |
| 228094620 | Party Two | `.B.Kishore` | `B.Kishore` | The label's leading dot looks like an artefact. The model's evidence quote shows the source as "Mr.B.Kishore", so the prediction is arguably the more faithful one, but it still counts as a miss. |

The remaining mismatches (all of Party One, and Party Two on `24158401`) are whitespace only.

### Notes on model behaviour

- Fields derived by calculation or fallback are marked `inferred` rather than `found`: both end dates computed from an 11-month term, and the notice period converted from "one month" or "two months" to 30 or 60 days.
- `95980236` was flagged `uncertain` on value and start date: the written rent amount disagrees with the figure, and the execution date (2005) precedes the lease start (2010). Both fields matched the labels.
- Image documents carry a warning that they were read in image batches and combined through model-generated transcription, so names and numbers should be checked against the source.

### Not yet measured

- **Train set:** no train run has been recorded, so only test results are reported.
- **Repeat-run variation:** only one run is reported. Language-model output can vary between runs, so treat the scores as one sample.

To reproduce:

```bash
python -m app.cli predict data/test --provider groq --output predictions/test_predictions.csv
python -m app.cli evaluate --predictions predictions/test_predictions.csv \
                           --labels data/test.csv --output predictions/test_metrics.json
```

On Groq's free tier, tall scans can exceed the per-minute input cap (see Limitations); the run above completed all four documents without failures.

---

## Known Dataset Issues

Confirmed with `python -m app.cli audit`. The original data is left unmodified.

- `24158401-Rental-Agreement` is labelled in **both** `train.csv` and `test.csv`, but its file exists only in `test/`. Do not use that train row when scoring.
- `46239065-Standard-Rental-Agreement-Rental-With-Performance-Fee` has no training label.
- Three training end dates are impossible calendar dates copied from the source: `31.11.2009` (`18325926`), `31.04.2011` (`36199312`), `31.02.2011` (`47854715`). The app now keeps such dates as written, with a warning.
- `44737744-Maddireddy-Bhargava-Reddy-Rental-Agreement` has a blank Renewal Notice label.
- Many names and dates have stray leading or trailing whitespace, which is why strict and trimmed scores differ.
- Some labels may contradict their documents (for example, `95980236` states an 11-month term from 1 April 2010, but the label end date `31.03.2011` implies 12 months).

---

## Tests

```bash
python -m pytest -q
```

Provider calls are mocked, so no API key or spending is needed, and `tests/conftest.py` blanks credentials so tests never use real keys. Several tests read the dataset, so `data/` must be present. Optional browser test:

```bash
npm install
npx playwright install chromium
npm run test:ui
```

---

## Supported Formats and Limits

**Primary (the assignment's scope):** `.docx` and scanned images (`.png`, `.jpg`, `.jpeg`).

**Secondary extras (built but not part of the evaluated scope):** `.pdf`, `.odt`, `.rtf`, `.webp`, `.tif`, `.bmp`, `.gif`, `.xlsx`, `.pptx`, `.txt`, `.md`, `.csv`, `.tsv`, `.json`, `.html`, `.xml`, `.eml`.

Per file: 20 MB, 30 pages, 40 image sections, 120,000 text characters. Legacy `.doc`/`.xls`/`.ppt`, password-protected files, HEIC, archives, audio and video are not supported.

---

## Limitations

- **Provider limits.** Free tiers can reject large scans. Groq counts each image as 2,048 input tokens regardless of its pixel size, and its free tier caps input at 7,000 tokens per minute for the default model. A request with three image slices therefore sits right at the cap, and a tall multi-page scan that needs a batch of three can exceed it (resizing the image does not help). Use a paid tier or OpenAI for the full test set. The error message now shows the provider's own text, so limit failures are easy to identify.
- **Format drift.** Some models occasionally return markdown instead of JSON on the Groq path; OpenAI's structured output avoids this.
- Built for single-user local use on `127.0.0.1`. There is no authentication, rate limiting or HTTPS; add these before exposing it to a network.
- Document content is sent to the selected provider (OpenAI requests set `store=False`; each provider's retention policy still applies).
- Evidence quotes and explanations are model-generated review aids, not verified citations or calibrated confidence. Review results before relying on them.
- Poor handwriting, blur, rotation or very small text can reduce accuracy.
