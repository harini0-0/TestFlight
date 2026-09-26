# AI procurement control

Local control plane for supplier documents. Upload contracts, rebates, discounts, service levels, renewal dates, and payment terms. Process them into one rule engine, approve it once, then check live invoices against it.

The page runs at [http://localhost:3000](http://localhost:3000). The API runs at [http://localhost:8000](http://localhost:8000).

## What you need

- macOS or Linux
- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 or newer
- pnpm 9

Install the tools if they are missing:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
corepack enable
corepack prepare pnpm@9 --activate
```

Postgres, Redis, and Docker are not required for the local demo. The API stores data in `var/glasswing.db` (SQLite) unless you set `DATABASE_URL`.

## Build

From the repository root:

```bash
uv sync --all-packages
pnpm install
```

`uv sync` installs every Python package in `packages/` and `services/`. `pnpm install` installs the Next.js app in `apps/web`.

## Run

Use two terminals.

```bash
make api
```

```bash
make web
```

Open [http://localhost:3000](http://localhost:3000). The home page signs you in as the local procurement manager. No password is required.

If `make` is unavailable, the same processes are:

```bash
uv run uvicorn gateway.main:app --app-dir services/gateway/src --reload --port 8000
pnpm --dir apps/web dev
```

To point the page at an API that is not on this machine:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm --dir apps/web dev
```

## Try the sample supplier

On the home page, click **Load Meridian Components**. That reads `samples/meridian/`, compiles one engine, confirms the rebate rules, and approves it. The live invoices are not posted yet.

Open **4. Live period** and click **Play live stream**. The files in `samples/meridian/live/` are posted in order. A leak pulses red on the rule and on the finding.

You can also start a workspace yourself and drop the text files from `samples/meridian/` into the matching upload boxes. Name the supplier **Meridian Components** if you want those live CSV files to match the workspace. On **2. Process**, confirm both rebate buttons, then click **Approve engine**. The table on that step is the built-in unit tests. Every row must pass before the engine can go live.

## Checks

```bash
make test
```

That runs the Python tests, Ruff, the domain type check, and the web format tests.

## Optional services

```bash
make compose
```

This starts Postgres (with pgvector), Redis, and LocalStack from `infra/docker-compose.yml`. The running app still uses SQLite until `DATABASE_URL` is set, for example:

```bash
DATABASE_URL=postgresql+psycopg://glasswing:glasswing@localhost:5432/glasswing make api
```

Leave `GLASSWING_ENV` unset on a demo machine. Setting it to `prod` hides the sample loaders.

## Folder names that contain `$`

Next.js rewrites `$$` inside a path. `apps/web/next.config.js` already keeps those paths intact, so a checkout whose folder name contains `$$` can still build.
