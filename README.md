# Guardian

A WhatsApp-first AI safety assistant.

A user forwards a suspicious WhatsApp message to Guardian's number. Guardian
analyses it and replies with a simple risk assessment and one safe action to
take.

> **Status: WhatsApp Web bridge + evidence-grounded reasoning.** A small Baileys
> bridge receives private text, image, and voice/audio messages, extracts screenshot
> text with local Tesseract OCR, transcribes audio with ElevenLabs, and sends
> Guardian's reply back over WhatsApp Web. FastAPI
> owns the existing signal, URL, SerpApi, and Gemma pipeline.
> No Meta Cloud API is used by the bridge. The React frontend remains a placeholder;
> a database is not built yet.

## Structure

```
.
├── backend/              FastAPI service
│   ├── app/
│   │   ├── api/          routers, route modules, error→status mapping
│   │   ├── core/         cross-cutting concerns (logging)
│   │   ├── schemas/      pydantic request/response models
│   │   ├── services/     business logic, isolated from HTTP
│   │   ├── config.py     settings loaded from the root .env
│   │   └── main.py       app factory + entrypoint
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/             React + TypeScript + Vite
│   └── src/
├── whatsapp-bridge/      Node.js/TypeScript Baileys transport
│   └── src/
├── tests/                pytest suite for the backend
├── .env.example
├── pytest.ini
└── README.md
```

The `services/` subpackages keep logic out of the HTTP layer:

| Package              | Status                                          |
| -------------------- | ----------------------------------------------- |
| `services/whatsapp/` | legacy webhook adapter; not used by the Baileys bridge |
| `services/processing/` | normalization, existing evidence collection, and configured Gemma reasoning |
| `services/analysis/` | deterministic text signals, URL extraction, lexical URL analysis |
| `services/url/`      | real SerpApi domain searches and concise source evidence |
| `services/reasoning/` | Gemma API client, safety prompt, and validated risk assessments |
| `services/evidence/` | persistence, audit trail, reports — not started |

## API

| Method | Path | What |
| --- | --- | --- |
| GET | `/` | service metadata |
| GET | `/health` | liveness probe |
| GET | `/docs` | interactive API docs |
| POST | `/api/bridge/messages` | authenticated normalized message → Guardian reply |

### WhatsApp communication with Baileys

```text
WhatsApp Web → whatsapp-bridge/ → FastAPI → existing analysis pipeline
             ← original sender ← reply ← Gemma assessment
```

The bridge authenticates with a QR or pairing code, retains its linked-device
session locally, and sends normalized `GuardianMessage` fields to FastAPI using
a shared bearer token. FastAPI formats the generated short explanation and
recommended action into a `reply`; Node sends it unchanged to the original
WhatsApp chat. Image messages are downloaded temporarily for local Tesseract OCR;
recognized text joins the same two-minute sender buffer as normal text. Images
are deleted after OCR, and extracted URLs use the existing backend analysis.
Voice notes/audio attachments use ElevenLabs STT (`ELEVENLABS_API_KEY`, configurable
`ELEVENLABS_STT_MODEL=scribe_v2`) with automatic language detection. Local temporary
audio is deleted after processing; transcripts enter that same buffer in arrival
order. Empty/failed voice notes get a friendly notice, appended to the unmodified
backend reply when other readable content exists. See the bridge README for audio
privacy limitations and English/Hindi/Hinglish manual checks.
Risk reasoning and URL evidence collection remain entirely in Python.

See **[whatsapp-bridge/README.md](whatsapp-bridge/README.md)** for setup, pairing,
session storage, reconnection, and operational limits. The older webhook adapter
remains in the repository for compatibility but is not part of this flow and
requires no configuration. No new Meta Cloud API implementation is added.

## Live URL verification

The existing URL extractor and signal detector are reused unchanged:

```text
GuardianMessage
  -> MessageProcessor: normalize text and timestamp
  -> SignalAnalyzer: extract URLs and detect offline signals
  -> UrlVerifier: query SerpApi once per distinct domain
  -> ProcessedMessage: normalized message + AnalysisResult with url_evidence
```

Set `GUARDIAN_SERPAPI_API_KEY` in the root `.env` to enable live lookups, then
restart the backend. Obtain a real key from [SerpApi](https://serpapi.com/manage-api-key).
There is no mock provider or fabricated fallback: with an empty key, Guardian
runs offline analysis only and `url_evidence` is empty.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `GUARDIAN_SERPAPI_API_KEY` | empty | Private SerpApi key; enables live verification |
| `GUARDIAN_SERPAPI_ENDPOINT` | `https://serpapi.com/search.json` | HTTPS search endpoint |
| `GUARDIAN_SERPAPI_TIMEOUT` | `10` | Timeout per HTTP operation, in seconds (>0, up to 30) |
| `GUARDIAN_SERPAPI_RESULTS_PER_DOMAIN` | `5` | Retained organic results per domain (1–10) |
| `GUARDIAN_SERPAPI_MAX_DOMAINS` | `5` | Maximum search requests per message (1–20) |

Only a sanitized hostname is sent in a query such as
`"example.com" (scam OR phishing OR fraud OR review)`. Message bodies, sender
identifiers, URL credentials, paths, and query tokens are not sent. Guardian
never visits the suspicious link, follows its redirects, or fetches result
pages. Search evidence therefore describes the domain, not proof about an
individual page or a shortened link's destination.

### Evidence contract

`MessageProcessor.process_with_analysis(message)` returns a `ProcessedMessage`:

- `message`: the normalized `GuardianMessage`.
- `analysis`: the existing `AnalysisResult`, enriched with `url_evidence`.
- Each evidence entry contains `url`, `domain`, `query`, `results`, and `error`.
- Each result contains the source `title`, source `url`, a `snippet` of at most
  300 characters (empty if the source provides none), and a `source` name/host.

There is one evidence entry per extracted URL, in the same order. URLs sharing
one domain reuse a lookup, including failed lookups. Invalid targets, private
IP addresses, exhausted per-message budgets, timeouts, provider errors, and
malformed responses produce explicit errors rather than dropping a message.
A successful search with no matches has empty `results` and no `error`.
**Neither an empty search nor a failed lookup means a URL is safe.** Results are
untrusted source material for Gemma's risk estimate, not themselves a verdict.

The app lifespan creates a shared SerpApi HTTP client, injects it into the
processor used by the API, and closes it on shutdown. The synchronous backend
waits for these bounded lookups; the bridge has a small in-memory queue, not a
durable job system. Raw evidence stays internal; only the formatted assessment
is returned to the bridge. Existing callers of `process(message)`
retain its normalized-message return value; callers needing evidence use
`process_with_analysis(message)`. Neither method persists evidence yet.

The integration follows SerpApi's [Google Search API](https://serpapi.com/search-api)
and [organic-results schema](https://serpapi.com/organic-results).

## Gemma risk reasoning

Guardian uses **open-weight Gemma**, not Gemini, through a real Chat Completions
API. The default is `google/gemma-3-27b-it` on OpenRouter. The same adapter works
with another OpenAI-compatible host or a locally served instruction-tuned Gemma
model; no provider SDK or local model download is required by Guardian itself.

```text
GuardianMessage
  -> existing SignalAnalyzer (text signals + lexical URL analysis)
  -> existing UrlVerifier (SerpApi evidence, when configured)
  -> GemmaReasoner (message + the same AnalysisResult)
  -> validated RiskAssessment
```

Enable hosted inference in the root `.env`, then restart the backend:

```dotenv
GUARDIAN_GEMMA_ENABLED=true
GUARDIAN_GEMMA_PROVIDER=openrouter
GUARDIAN_GEMMA_BASE_URL=https://openrouter.ai/api/v1
GUARDIAN_GEMMA_MODEL=google/gemma-3-27b-it
GUARDIAN_GEMMA_API_KEY=<your-provider-key>
```

Keep `GUARDIAN_SERPAPI_API_KEY` configured to supply live URL evidence too.
Without it, Gemma receives the existing offline signals and URL analysis;
missing search evidence is explicitly not proof of safety.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `GUARDIAN_GEMMA_ENABLED` | `false` | Explicitly enable transmission of message content and evidence |
| `GUARDIAN_GEMMA_PROVIDER` | `openrouter` | `openrouter` or `openai_compatible` |
| `GUARDIAN_GEMMA_BASE_URL` | `https://openrouter.ai/api/v1` | API base; `/chat/completions` is appended |
| `GUARDIAN_GEMMA_API_KEY` | empty | Bearer API key; required remotely, optional on loopback |
| `GUARDIAN_GEMMA_MODEL` | `google/gemma-3-27b-it` | Provider's Gemma model ID or a served alias containing `gemma` |
| `GUARDIAN_GEMMA_TIMEOUT` | `30` | Timeout per HTTP operation, in seconds (>0, up to 120) |
| `GUARDIAN_GEMMA_MAX_TOKENS` | `1024` | Maximum generated tokens (128–4096) |
| `GUARDIAN_GEMMA_MAX_INPUT_CHARS` | `60000` | Full prompt character budget, including schema (4096–200000) |
| `GUARDIAN_GEMMA_RESPONSE_FORMAT` | `json_schema` | `json_schema` or explicitly selected `json_object` mode |

For a real local vLLM server, set the provider to `openai_compatible`, the base
URL to `http://127.0.0.1:8001/v1`, and the model to the Gemma model/alias your
server exposes (for example `google/gemma-3-4b-it`). You must run that inference
server and obtain the weights separately. Remote endpoints require HTTPS;
plain HTTP is allowed only for `localhost`, `127.0.0.1`, or `::1`.

### Structured assessment

The existing `processor.process_with_analysis(message)` now also returns:

- `risk_assessment`: a validated `RiskAssessment`, or `None` if unavailable.
- `reasoning_error`: empty on success; a safe diagnostic when disabled or failed.

The assessment has exactly these required fields:

| Field | Contract |
| --- | --- |
| `response_language` | `english`, `hindi` (Devanagari), or `hinglish` (Roman Hindi) |
| `risk_level` | `LOW`, `MEDIUM`, or `HIGH` — an estimate, not a scam verdict |
| `confidence` | Finite number in `[0, 1)`; model-estimated, not calibrated probability |
| `reasons` | 1–6 concise, nonempty explanations grounded in supplied evidence |
| `evidence_used` | 1–20 JSON pointers into the message/analysis supplied to Gemma |
| `recommended_action` | A nonempty safe next step, at most 600 characters |
| `short_user_explanation` | A nonempty plain-language explanation, at most 500 characters |

For example, `/analysis/signals/0` identifies the first existing signal and
`/analysis/url_evidence/0/results/0` identifies the first source result for the
first URL. `/message/text` identifies the forwarded text. Every cited pointer
is checked against the evidence actually supplied. The full original
`result.analysis` remains available; the reasoning layer does not rerun URL
extraction, repeat SerpApi lookups, or replace deterministic signals.

### Response language

Gemma selects `response_language` in the same reasoning call; there is no extra
language-detection service or translation API. All reasons, the short explanation,
and recommended action must use that style:

- English prose → English.
- Hindi in Devanagari → Hindi in Devanagari.
- Roman Hindi or mixed English/Hindi prose → natural Hinglish/Roman Hindi.
- URL-only or insufficient text → English, unless other text/captions in the
  same two-minute batch provide enough language context.

Language selection uses the actual buffered message and OCR content, not English
OCR labels, generated failure notices, signal explanations, or search results.
URLs, domains, evidence titles, and technical identifiers are not translated.
The WhatsApp heading remains `Guardian — HIGH RISK`, `MEDIUM RISK`, or `LOW RISK`;
the explanation and action label follow the selected language. Replies use three
short sections: risk level, **Why**, and **What to do** (localized for Hindi and
Hinglish). The formatter keeps complete sentences within 240 characters for the
explanation and 180 for the generated action, with neutral wording if no sentence
fits. A short conditional reminder always directs money/OTP/password/PIN/login
requests to the organisation's official app, independently opened website, or
trusted official phone number—not the received message/link. Confidence percentages,
raw search results, and OCR dumps are omitted. Numeric certainty claims are not
forwarded; the assessment itself is unchanged. Existing transport-error notices
stay unchanged when no assessment is available.

OCR itself is unchanged and still uses Tesseract's English language data; this
feature does not add Devanagari OCR recognition. Any recognized text follows the
same language-selection rules. No risk heuristics or evidence logic changed.

For a manual check, send each of these **as a separate batch** from another
WhatsApp account. Wait two minutes of inactivity and receive the reply before
sending the next, so the languages do not get combined:

1. English: `Someone is asking for my password to unlock my account. What should I do?`
2. Hindi: `कोई मेरा खाता खोलने के लिए मेरा पासवर्ड माँग रहा है। मुझे क्या करना चाहिए?`
3. Hinglish: `Koi mera account unlock karne ke liye password maang raha hai. Main kya karun?`

Expect the matching language/script for each explanation and action, with the
same English risk-label format. Risk ratings are model-generated, not fixed.

The safety prompt explicitly forbids certainty claims and invented evidence,
requires reasoning from supplied observations, and recommends independent
verification before payments or sharing credentials/OTPs. Message text and
search snippets are treated as **untrusted data**, not instructions. Gemma 3's
system-level instructions go in its initial user turn, as required by its chat
template. Only concise reasons are requested, not a chain-of-thought transcript.

The client requests JSON Schema output by default. Hosts that support JSON mode
but not schemas can use `json_object`; local validation is still mandatory.
Invalid schemas, unknown evidence references, refusals, truncated completions,
provider errors, and oversized inputs leave the assessment unavailable. Guardian
never fabricates an AI response, repairs invalid JSON into an assessment,
substitutes a different model, or falls back to a heuristic LOW rating. A prompt
and valid citations do **not** guarantee that the model's prose is correct;
assessments remain uncertain and should guide safer verification, not replace it.

**Privacy and operations:** Unlike domain-only SerpApi requests, Gemma receives
forwarded message text and the collected evidence, including original URLs.
Sender IDs, message IDs, and transport timestamps are omitted, but the text or
URLs may themselves contain personal information or secrets. Choose a provider
with appropriate retention policies, or self-host. Prompts, model responses,
and credentials are not logged. Both HTTP pools are managed by the app lifespan
and closed on shutdown. Backend processing remains synchronous; API latency adds
to delivery time. The bridge endpoint returns only the formatted risk estimate,
short explanation, and recommended action for WhatsApp delivery. The full
assessment and raw evidence are not exposed to Node or persisted.

References: [Gemma prompt formatting](https://ai.google.dev/gemma/docs/core/prompt-structure),
[Gemma 3 27B on OpenRouter](https://openrouter.ai/google/gemma-3-27b-it),
[structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs),
and [vLLM serving](https://docs.vllm.ai/en/latest/serving/online_serving/).

## Prerequisites

- Python 3.11+
- Node.js 20.19+ (required by the WhatsApp bridge)
- Tesseract CLI with English (`eng`) language data for local screenshot OCR

## Setup

```bash
git clone <repo-url>
cd Guardian-HacktoberFest-26
cp .env.example .env
```

The backend, frontend, and WhatsApp bridge read this single root `.env`. Only
`VITE_`-prefixed variables reach the browser bundle — never put a secret
behind a `VITE_` prefix.

Set `GUARDIAN_WHATSAPP_BRIDGE_TOKEN` to a random secret of at least 32 characters
(`openssl rand -hex 32`). Configure Gemma for generated replies and SerpApi for
live URL evidence. No Meta credentials or public WhatsApp webhook are needed.

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt

uvicorn app.main:app --reload --app-dir backend
```

See [API](#api) for the available endpoints, or open
http://127.0.0.1:8000/docs.

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so there is no CORS
setup needed locally.

### WhatsApp bridge

With FastAPI running and the shared token and Gemma configured:

```bash
cd whatsapp-bridge
npm ci
npm run build
npm start
```

Scan the terminal QR using WhatsApp's **Linked devices** screen. For pairing-code
login, set `WHATSAPP_PAIRING_PHONE` to the account's country code + number (digits
only). Authentication is saved in the gitignored `whatsapp-bridge/.auth/` folder.

Baileys is unofficial: use a dedicated account with consenting users, respect
WhatsApp's terms, and understand the risk of account restrictions. The transport
is free/open-source, but hosted Gemma, SerpApi, and hosting may still cost money.

## Tests

Run from the repo root:

```bash
pytest
```

## Scripts

| Command                                       | What it does                 |
| --------------------------------------------- | ---------------------------- |
| `uvicorn app.main:app --reload --app-dir backend` | run the API with hot reload |
| `pytest`                                      | run the backend test suite   |
| `npm run dev` (in `frontend/`)                | run the Vite dev server      |
| `npm run build` (in `frontend/`)              | type-check and build for prod |
| `npm run lint` (in `frontend/`)               | lint the frontend            |
| `npm run build` (in `whatsapp-bridge/`)       | type-check and compile the bridge |
| `npm start` (in `whatsapp-bridge/`)           | run the compiled Baileys bridge |
| `npm run dev` (in `whatsapp-bridge/`)         | run the bridge directly from TypeScript |

## Contributing

Issues and pull requests are welcome. Please keep the backend layering intact:
routes stay thin, logic lives in `app/services/`.
