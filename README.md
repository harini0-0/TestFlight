# AccioRebate

**An AI procurement control plane that recovers negotiated savings before they are paid away.**

AccioRebate compiles your supplier paperwork (contracts, rebates, discounts, SLAs, renewals, payment terms) into one rule engine a human approves once, then checks every invoice automatically and flags any overcharge, unclaimed rebate, or expired discount with the exact clause and the dollars at risk.

Built at the **TestFlight Hackathon by Glasswing Ventures**, sponsored by **The Open Accelerator**, **Amazon Web Services (AWS)**, and **Microsoft**.

<p align="left">
  <img alt="Next.js" src="https://img.shields.io/badge/Next.js-15-black?logo=next.js">
  <img alt="React" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5.7-3178C6?logo=typescript&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white">
  <img alt="Postgres" src="https://img.shields.io/badge/Postgres-pgvector-4169E1?logo=postgresql&logoColor=white">
  <img alt="DeepSeek" src="https://img.shields.io/badge/LLM-DeepSeek%20V4.1%20Flash-5A5AFF">
  <img alt="AWS" src="https://img.shields.io/badge/AWS-Bedrock%20%C2%B7%20SQS%20%C2%B7%20EventBridge-FF9900?logo=amazonaws&logoColor=white">
  <img alt="Render" src="https://img.shields.io/badge/Deploy-Render-46E3B7?logo=render&logoColor=white">
</p>

🔗 **Live:** https://glasswing-web.onrender.com &nbsp;·&nbsp; 💻 **Code:** https://github.com/harini0-0/TestFlight

---

## 📹 Product demo

<video src="https://github.com/harini0-0/TestFlight/raw/main/Demo/demo.mp4" controls width="100%"></video>

> If the player above does not load in your Markdown viewer, watch it here:
> **[▶ Watch the demo](Demo/demo.mp4)**

[![AccioRebate demo](Demo/screenshot.png)](Demo/demo.mp4)

*Click the screenshot to play the full walkthrough. The pitch deck is in [`Demo/Accio_Rebate_Pitch (1).pdf`](Demo/Accio_Rebate_Pitch%20(1).pdf).*

---

## 📊 Product analysis

### The problem
Rebates, volume discounts, early-pay discounts, and SLA penalty credits are all negotiated into supplier contracts, then invoices are never checked against them. The money is already earned, and it is quietly paid away.

| Signal | Figure | Source |
| --- | --- | --- |
| Value leaked on supplier spend | **~$40M / year on $2B of spend (~2%)** | McKinsey |
| Companies with anyone owning contracts after signing | **Under 30%** | Deloitte / WorldCC |

### Who it is for
The **CFO at a mid-size manufacturer** who owns the leaking margin, has thousands of supplier invoices, and is too small to interest the recovery-audit firms that serve the Fortune 1000.

### Value it creates
Estimated for a manufacturer with **~$500M of supplier spend**:

| Outcome | Estimate |
| --- | --- |
| Dollars recovered per year | **$2.5M – $5M** (of ~$10M at stake) |
| Review hours saved per year | **3,800 – 7,500 hrs** (2–4 analysts' workload) |

*Assumes ~50,000 invoices/year, 5–10 min per manual check, ~1 in 10 flagged, 0.5–1% of spend recovered. A real AI pilot found $10M+ in 4 weeks (McKinsey).*

### How it is different from recovery audits
| | Recovery audit firms (e.g. PRGX) | **AccioRebate** |
| --- | --- | --- |
| Who it serves | Mostly Fortune 1000 | **Mid-size companies too** |
| How it is paid | Keeps a % of what it recovers | **Software the company runs itself** |
| When it catches | After payment, periodic audits | **Every invoice, on arrival, before payment** |
| How it works | Specialist teams, their own tools | **Rules compiled from each clause; every flag traces to the contract** |
| Supplier impact | Clawbacks after the fact | **Caught before payment, so fewer clawbacks** |

---

## 🧠 How the AI works

The AI is not a chatbot bolted on, it **is the compiler**. The model is **DeepSeek-V4.1-Flash**, served over an OpenAI-compatible endpoint, called at `temperature=0` with schema-validated JSON output.

| Agent | Job |
| --- | --- |
| **Compiler** | Reads each clause and turns it into a structured, testable rule (`condition` where math applies, `natural_language` only for the remainder). |
| **Test generator** | Writes contract-specific unit tests so every rule is proven before the engine goes live. |
| **NL judge** | Judges the fuzzy clauses that cannot be reduced to math → `pass` / `violation` / `escalate`, with a clause citation. |
| **Investigator** | A tool-using agent (`get_clause`, `get_invoice_lines`, `get_ledger`, `search_clauses`) that finds root cause, confidence, a recommended action, and can propose a rule patch. |

**Design principles**
- **Compiled once, then no AI call per invoice** — rules run deterministically, so checks are fast, cheap, and auditable.
- **The AI compiles and judges, but the dollar math stays deterministic**, and a human approves every engine before it goes live.
- **Ambiguity is escalated, not guessed** — an unclear rebate clause is flagged `needs_confirmation` for a person.
- **Hardened for the enterprise** — `temperature=0`, schema-validated JSON with retry, prompt-injection defenses that treat contract text as untrusted, clause retrieval over vector embeddings, and a deterministic fallback model when no API key is set.

---

## 🏗️ Architecture & tech stack by stage

```
Supplier docs ─▶ Ingestion ─▶ Compilation (AI) ─▶ Human approval ─▶ Control engine ─▶ Investigation (AI) ─▶ Actions ─▶ Audit
                                                                         ▲                                           │
                                                                         └──────────── Event bus (outbox) ──────────┘
```

| Stage | What happens | Service / module | Tech |
| --- | --- | --- | --- |
| **1. Ingestion** | Supplier documents and invoices become canonical events; ERP field names never leak downstream. | `ingestion` (`connectors`, `normalize`, `local_invoice`) | Python 3.12, `pypdf`, `openpyxl`, CSV/JSON parsing |
| **2. Compilation** | Each clause is compiled into versioned Rule IR; cross-document clause references and pricing are resolved; unit tests are generated. | `compiler` (`llm_compile`, `pipeline`, `references`, `pricing`, `testgen`) | FastAPI, **DeepSeek-V4.1-Flash**, Pydantic 2 |
| **3. Human approval** | Generated unit tests must pass; ambiguous clauses require confirmation before the engine is approved. | `gateway` (`platform`) | FastAPI, SQLAlchemy 2.0 |
| **4. Control engine** | Pure, deterministic evaluators run every invoice against the approved rules; ledger math is isolated from sandbox runs. | `control-engine` (`evaluators`, `ledger`, `sandbox`) | Python (no I/O in evaluators), deterministic |
| **5. Investigation** | Exceptions are explained with root cause and a recommended fix; relevant clauses are retrieved by similarity. | `investigator` (`service`) | **DeepSeek-V4.1-Flash** (tool use), vector embeddings / pgvector |
| **6. Actions** | Outbound actions (notify, draft supplier dispute, open ticket, ERP adjustment); high-risk ERP writes require an approval row. | `actions` (`machine`) | Python state machine |
| **7. Audit** | Every state change is written to an append-only, hash-chained log with no update or delete API. | `audit` (`chain`) | Python, hash-chaining |
| **Eventing** | A transactional outbox relays unpublished rows to the event bus. | `adapters` (`relay`, `bedrock`, `db`, `runtime`) | AWS EventBridge + SQS, Bedrock (optional), boto3, LocalStack |

### Frontend
- **Next.js 15** (App Router), **React 19**, **TypeScript 5.7**, **Tailwind CSS 3.4**
- Visualizations: **@visx/sankey** (dollar-flow), **Recharts** (value bands)
- Pages: `work`, `contracts`, `findings`, `portfolio`, `roi`, `audit`, `admin`

### Backend & domain
- **Python 3.12**, **FastAPI 0.115**, **Uvicorn**, **SQLAlchemy 2.0**, **Pydantic 2.9**, **httpx**
- Domain core (`glasswing-domain`): rule IR, money math, periods/windows, events, ontology, prompts, JSON extraction

### Data & infrastructure
- **SQLite** for the local demo; **Postgres + pgvector** for production retrieval
- **Redis** (caching/queues), **AWS S3** (document blobs, LocalStack for local dev)
- **Docker Compose** (`infra/docker-compose.yml`), **Terraform** (`infra/terraform/main.tf`), SQL schema (`infra/sql/001_schemas.sql`)
- Deployed on **Render**

### Tooling & quality
- **uv** (Python packaging), **pnpm 9** (JS workspace), **Ruff** (lint), **pytest** + **Hypothesis** (property tests), domain type checks

---

## 🚀 Getting started

> The project lives in the [`glasswing/`](glasswing/) directory. Run the commands below from there.

### Prerequisites
- macOS or Linux
- Python 3.12 · [uv](https://docs.astral.sh/uv/)
- Node.js 20+ · pnpm 9

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
corepack enable
corepack prepare pnpm@9 --activate
```

Postgres, Redis, and Docker are **not** required for the local demo. The API stores data in `var/glasswing.db` (SQLite) unless you set `DATABASE_URL`.

### Build

```bash
cd glasswing
uv sync --all-packages
pnpm install
```

### Run (two terminals)

```bash
make api   # FastAPI on http://localhost:8000
make web   # Next.js on http://localhost:3000
```

The home page signs you in as the local procurement manager (no password). If `make` is unavailable:

```bash
uv run uvicorn gateway.main:app --app-dir services/gateway/src --reload --port 8000
pnpm --dir apps/web dev
```

Point the page at a remote API:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm --dir apps/web dev
```

### Enable the AI compiler
Set an OpenAI-compatible endpoint and key (see `glasswing/.env.example`):

```bash
GLASSWING_LLM_BASE_URL=https://api.sciforium.com/v1
GLASSWING_LLM_API_KEY=your_key_here
```

Without a key, the engine falls back to a deterministic recording model.

### Try the sample supplier
1. On the home page, click **Load Meridian Components** — this reads `samples/meridian/`, compiles one engine, confirms the rebate rules, and approves it.
2. Open **4. Live period** and click **Play live stream** — the files in `samples/meridian/live/` post in order, and a leak pulses red on the rule and the finding.

You can also build a workspace by hand: drop the text files from `samples/meridian/` into the matching upload boxes (name the supplier **Meridian Components** so the live CSVs match), confirm both rebate buttons on **2. Process**, then click **Approve engine**. Every unit-test row must pass before the engine can go live.

### Tests

```bash
make test   # Python tests, Ruff, domain type check, web format tests
```

### Optional backing services

```bash
make compose   # Postgres (pgvector), Redis, LocalStack
DATABASE_URL=postgresql+psycopg://glasswing:glasswing@localhost:5432/glasswing make api
```

Leave `GLASSWING_ENV` unset on a demo machine; setting it to `prod` hides the sample loaders.

---

## 📁 Repository layout

```
TestFlight/
├── Demo/                 # Demo video, screenshot, pitch deck
├── glasswing/            # The application
│   ├── apps/web/         # Next.js + React frontend
│   ├── services/         # gateway, compiler, control-engine, ingestion,
│   │                     #   investigator, actions, audit
│   ├── packages/         # domain (rule IR, money, prompts) + adapters (llm, db, aws)
│   ├── samples/          # Meridian sample supplier pack + live stream
│   └── infra/            # docker-compose, terraform, sql
└── README.md
```

---

## 👥 Team — Accio_Rebate

- **Harini Thirunavukkarasan** — [@harini0-0](https://github.com/harini0-0)
- **Tashwin Sasalu Jagadeesha** — [@Tashwinsj](https://github.com/Tashwinsj)
- **Lavanya Ramasamy** — [@rlavanya1597](https://github.com/rlavanya1597)

## 🙏 Acknowledgements
Huge thanks to the **Glasswing Ventures** team, **The Open Accelerator**, **Amazon Web Services (AWS)**, and **Microsoft** for hosting TestFlight. Building something end to end on a deadline teaches you more than a semester of theory.
