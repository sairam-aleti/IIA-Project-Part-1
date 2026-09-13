# MoT Vehicle Integration — Part A

A **Global-As-View federated mediator** over five autonomous, heterogeneously
designed databases, built to identify uninsured and otherwise non-compliant
vehicles from roadside sightings — and to say so only when the evidence
supports it.

CSE656 Information Integration and Application, IIIT Delhi.

---

## What it does

- Discovers the mapping from a global schema to 32 local columns across five
  sources at run time. No column names are hardcoded anywhere in the query path.
- Resolves vehicle identity across five incompatible plate formats. A raw
  equi-join across these sources recovers **zero** vehicles; canonicalisation
  recovers 791–945 per source pair.
- Evaluates insurance **at the moment the vehicle was observed**, over a full
  policy history, rather than against today.
- Detects six classes of cross-source contradiction and reports them instead of
  silently choosing a winner.
- Reaches one of **four** outcomes, the fourth being `INSUFFICIENT_EVIDENCE` —
  the system can decline to conclude, and says why.
- Files findings to `mot.db`, the Ministry's reporting sink, with full evidence.

---

## Setup

```bash
python -m venv iia_project
source iia_project/bin/activate        # Windows: .\iia_project\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python data_generator.py                        # build the five source DBs
python -m uvicorn main:app --port 8000          # start the API + UI
```

Open <http://127.0.0.1:8000>. API docs at `/docs`.

## Verify

```bash
python verify.py          # nine sections of evidence for every claim made
python matcher_eval.py    # matcher accuracy under column renaming
```

`verify.py` is the script to run in the demo.

---

## Running without a network

The schema matcher prefers `sentence-transformers`, which downloads a model on
first use. If it is unavailable — no network, blocked host, cold cache — the
matcher falls back to lexical plus type scoring, reports that it has done so at
`GET /health` and in its startup output, and still derives the mapping rather
than hardcoding it. To force that path:

```bash
IIA_MATCHER_MODE=lexical python -m uvicorn main:app --port 8000
```

To pre-cache the model so the demo never waits on a download:

```bash
IIA_MODEL_DIR=./models python -c "from sentence_transformers import SentenceTransformer as S; S('all-MiniLM-L6-v2', cache_folder='./models')"
```

**The frontend still loads React, Babel and Inter from CDNs** (see
`static/index.html`). Vendor these into `static/` before demo day if the venue's
network is unreliable.

---

## Layout

| File | Role |
|---|---|
| `plate.py` | Plate canonicalisation; the deterministic identity layer |
| `data_generator.py` | Builds five isolated sources with divergent schemas and ragged coverage |
| `schema_matcher.py` | Attribute-level discovery: semantic + lexical + type, with instance evidence for the join key |
| `link_index.py` | Identity as a table — canonical mark to raw values, with method and score per link |
| `wrappers.py` | One wrapper per source, configured entirely by the discovered mapping |
| `mediator.py` | Dispatch, merge, temporal evaluation, contradiction detection, assessment, reporting |
| `main.py` | FastAPI surface, paginated, with compensating rollback on writes |
| `verify.py` | Evidence harness |
| `matcher_eval.py` | Matcher robustness measurement |
| `static/` | React single-page UI |

## Key endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/vehicle/{plate}?as_of=` | Global view for one plate, assessed at an instant |
| `GET /api/v1/vehicles?limit=&offset=&outcome=` | Paginated assessment |
| `GET /api/v1/vehicles/flagged` | Everything not compliant |
| `GET /api/v1/unresolved` | Reads the system cannot attribute |
| `GET /api/v1/schema-mapping` | The discovered mapping, with scores |
| `GET /api/v1/link-index` | Identity resolution statistics |
| `GET /api/v1/rules` | The declared conflict-resolution rules |
| `GET /api/v1/canonicalise/{plate}` | What canonicalisation does to a raw string |
| `POST /api/v1/sweep` | Assess and report in bulk |
| `GET /api/v1/reports` | The Ministry's report log |

---

See [project_report.md](./project_report.md) for the architecture, the
measured results, the conflict-resolution rules, stated limitations, and viva
preparation.
