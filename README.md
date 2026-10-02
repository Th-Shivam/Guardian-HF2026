# Guardian

A WhatsApp-first AI safety assistant.

A user forwards a suspicious WhatsApp message to Guardian's number. Guardian
analyses it and replies with a simple risk assessment and one safe action to
take.

> **Status: foundation only.** This repo currently contains the project
> skeleton — a running FastAPI backend and a running React frontend. There is
> no AI, no WhatsApp integration, no database and no UI beyond a placeholder.

## Structure

```
.
├── backend/              FastAPI service
│   ├── app/
│   │   ├── api/          routers and route modules
│   │   ├── core/         cross-cutting concerns (logging)
│   │   ├── schemas/      pydantic request/response models
│   │   ├── services/     business logic seams (all empty for now)
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

The `services/` subpackages mark where future capabilities go, so routes can
depend on them without the HTTP layer and the logic growing into each other:

| Package              | Future responsibility                          |
| -------------------- | ---------------------------------------------- |
| `services/whatsapp/` | webhook verification, inbound/outbound messages |
| `services/analysis/` | AI risk assessment of a forwarded message       |
| `services/url/`      | link extraction, redirect expansion, reputation |
| `services/evidence/` | persistence, audit trail, shareable reports     |

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

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt

uvicorn app.main:app --reload --app-dir backend
```

| URL                           | What                        |
| ----------------------------- | --------------------------- |
| http://127.0.0.1:8000/        | service metadata            |
| http://127.0.0.1:8000/health  | liveness probe              |
| http://127.0.0.1:8000/docs    | interactive API docs        |

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so there is no CORS
setup needed locally. Feature routers will be mounted under `/api`.

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
