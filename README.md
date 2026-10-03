# Guardian

A WhatsApp-first AI safety assistant.

A user forwards a suspicious WhatsApp message to Guardian's number. Guardian
analyses it and replies with a simple risk assessment and one safe action to
take.

> **Status: evidence collection.** The FastAPI webhook normalises inbound
> messages, detects deterministic risk signals, and optionally collects real
> domain-search evidence through SerpApi. The React frontend remains a
> placeholder. There is no AI verdict, outbound delivery, or database yet.

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
├── tests/                pytest suite for the backend
├── .env.example
├── pytest.ini
└── README.md
```

The `services/` subpackages keep logic out of the HTTP layer:

| Package              | Status                                          |
| -------------------- | ----------------------------------------------- |
| `services/whatsapp/` | inbound webhook + verification (outbound is a stub) |
| `services/processing/` | normalization, offline analysis, and optional live evidence |
| `services/analysis/` | deterministic text signals, URL extraction, lexical URL analysis |
| `services/url/`      | real SerpApi domain searches and concise source evidence |
| `services/evidence/` | persistence, audit trail, reports — not started |

## API

| Method | Path                    | What                                  |
| ------ | ----------------------- | ------------------------------------- |
| GET    | `/`                     | service metadata                      |
| GET    | `/health`               | liveness probe                        |
| GET    | `/docs`                 | interactive API docs                  |
| GET    | `/api/whatsapp/webhook` | subscription handshake                |
| POST   | `/api/whatsapp/webhook` | receive an inbound message payload    |

### Webhook verification

Providers confirm ownership of the endpoint by calling it with a challenge.
Guardian echoes the challenge back as **raw text** only when `hub.verify_token`
matches `GUARDIAN_WHATSAPP_VERIFY_TOKEN` (compared in constant time).

```bash
curl "http://127.0.0.1:8000/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=$TOKEN&hub.challenge=12345"
# -> 12345        (text/plain, 200)
# -> 403 if the token or mode is wrong
# -> 500 if GUARDIAN_WHATSAPP_VERIFY_TOKEN is unset — it fails closed
```

### Receiving a message

```bash
curl -X POST http://127.0.0.1:8000/api/whatsapp/webhook \
  -H 'Content-Type: application/json' \
  -d '{"object":"whatsapp_business_account","entry":[{"id":"1","changes":[{"field":"messages",
       "value":{"messaging_product":"whatsapp",
       "contacts":[{"wa_id":"16505551234","profile":{"name":"Asha"}}],
       "messages":[{"id":"wamid.ABC","from":"16505551234","timestamp":"1700000000",
                    "type":"text","text":{"body":"claim your prize"}}]}}]}]}'
```

```json
{
  "status": "received",
  "provider": "meta",
  "accepted": 1,
  "ignored": 0,
  "messages": [
    { "message_id": "wamid.ABC", "sender": "16505551234", "timestamp": "2023-11-14T22:13:20Z" }
  ]
}
```

Two deliberate behaviours:

- **The acknowledgement never echoes the message body.** Guardian handles
  content people believe is malicious; reflecting it into provider logs serves
  no purpose.
- **A valid envelope with nothing to analyse still returns 200** with
  `accepted: 0`. Delivery receipts and unsupported media types land on the
  same webhook, and providers disable endpoints that keep returning errors.
  Only genuinely malformed bodies return 422.

### Swapping providers

Routes depend on the abstract `WhatsAppProvider`, never on a concrete adapter.
Meta's Cloud API payload shape lives entirely in
`app/services/whatsapp/meta.py`. To add another backend, implement the
interface in `base.py` and register it in `registry.py`; selection is the
`GUARDIAN_WHATSAPP_PROVIDER` env var.

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
untrusted source material for a future risk decision, not an AI-generated verdict.

The app lifespan creates a shared SerpApi HTTP client, injects it into the
processor used by the webhook, and closes it on shutdown. The synchronous
webhook handler waits for these bounded lookups; there is no background queue
or cross-delivery deduplication yet. Evidence stays internal rather than being
reflected in the webhook acknowledgement. Existing callers of `process(message)`
retain its normalized-message return value; callers needing evidence use
`process_with_analysis(message)`. Neither method persists evidence yet.

The integration follows SerpApi's [Google Search API](https://serpapi.com/search-api)
and [organic-results schema](https://serpapi.com/organic-results).

## Prerequisites

- Python 3.11+
- Node.js 18+

## Setup

```bash
git clone <repo-url>
cd Guardian-HacktoberFest-26
cp .env.example .env
```

Both the backend and the frontend read this single root `.env`. Only
`VITE_`-prefixed variables reach the browser bundle — never put a secret
behind a `VITE_` prefix.

Set `GUARDIAN_WHATSAPP_VERIFY_TOKEN` to any string you choose; it is the
shared secret you also enter in the provider's webhook settings.

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

## Contributing

Issues and pull requests are welcome. Please keep the backend layering intact:
routes stay thin, logic lives in `app/services/`.
