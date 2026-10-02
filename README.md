# Guardian

A WhatsApp-first AI safety assistant.

A user forwards a suspicious WhatsApp message to Guardian's number. Guardian
analyses it and replies with a simple risk assessment and one safe action to
take.

> **Status: early foundation.** A running FastAPI backend, a running React
> frontend, and a WhatsApp webhook that accepts and normalises inbound
> messages. There is no AI, no outbound delivery, no database and no UI
> beyond a placeholder — nothing is analysed or stored yet.

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
| `services/analysis/` | AI risk assessment — not started                |
| `services/url/`      | link extraction, redirect expansion, reputation — not started |
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
