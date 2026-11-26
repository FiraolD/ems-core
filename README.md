# EMS: employee management system

Payroll, attendance, tax and pension for companies, installed separately for each client.
One core codebase; each client's differences live in their own `client.toml` and extension
package, never in core.

## Layout

| Folder | Purpose |
|---|---|
| `config/` | Django settings (`base`, `dev`, `prod`, `test`), URLs, Celery, WSGI |
| `core/` | Platform pieces with no business domain: client config loader, hook registry, health endpoints |
| `modules/` | Business modules, each switched on per client (`hr` now; attendance, leave, overtime, payroll next) |
| `countries/` | Statutory rules per country (Ethiopia, `et`, arrives with payroll) |
| `gateways/` | Separate services, such as the attendance device gateway |
| `clients/_template/` | Blank starting point for a new client |
| `deploy/` | Dockerfile, Docker Compose, `.env.example` |

Core never imports from `modules` or clients. Modules depend on `core`. Client packages depend
on core, never the reverse.

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                      # unit tests, in-memory SQLite
```

For a development server you need PostgreSQL (set `DB_*` variables), then:

```bash
python manage.py migrate
python manage.py runserver
```

No PostgreSQL on your machine? For trying things out only, set `EMS_DEV_SQLITE=1` to use a local
SQLite file (`db.sqlite3`, ignored by git). It has no database-level audit-log protection, so never
use it for real data. In PowerShell:

```powershell
$env:EMS_DEV_SQLITE = "1"
python manage.py migrate
python manage.py sync_roles
python manage.py createsuperuser
python manage.py seed_tax_schedule
python manage.py seed_leave_types
python manage.py seed_overtime_categories
python manage.py runserver
```

## How a client is configured

Each install points `EMS_CLIENT_CONFIG` at the client's `client.toml`. It sets company details,
enabled modules, the country pack and pay-rule overrides. Invalid files are rejected at start-up
with every problem listed. Money rates are written as quoted text (`"0.07"`), never as numbers.

Behaviour that settings cannot express goes in the client's extension package: a
`register(registry)` function that attaches to hooks core declares. Hooks must be declared first,
so a mistyped hook name fails loudly. Client templates and static files placed next to
`client.toml` override the defaults.

## Install for a client

```bash
cd deploy
cp .env.example .env        # set SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS
EMS_CLIENT_DIR=/path/to/client-repo docker compose up -d --build
```

Production refuses to start without a strong `SECRET_KEY`, `ALLOWED_HOSTS` and an explicit
`EMS_CLIENT_CONFIG`, or when the client enables a module that is not installed.
`/healthz` reports liveness and `/readyz` reports database connectivity.
