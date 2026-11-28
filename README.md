# EMS: employee management system

Payroll, attendance, tax and pension for companies, installed separately for each client.
One core codebase; each client's differences live in their own `client.toml` and extension
package, never in core.

## Layout

| Folder | Purpose |
|---|---|
| `config/` | Django settings (`base`, `dev`, `prod`, `test`), URLs, Celery, WSGI |
| `core/` | Platform pieces with no business domain: client config loader, hook registry, health endpoints |
| `modules/` | Business modules, each switched on per client: `hr`, `attendance`, `leave`, `overtime`, `payroll` |
| `countries/` | Statutory rules per country (Ethiopia, `et`) |
| `gateways/` | Separate services, such as the attendance device gateway |
| `clients/_template/` | Blank starting point for a new client |
| `clients/_sample_workshop/` | A made-up second client that shows what can differ (modules, rules, extension). Used by the tests; not a real customer |
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

## Create a client

1. Copy `clients/_template` into the client's own private repository (for example `ems-client-acme`).
   Core never contains a real client's name.
2. Edit `client.toml`: company details, the modules they bought, the country pack and any pay-rule
   overrides (rates as quoted text, such as `"0.07"`). Mistakes are reported all at once at start-up.
3. Behaviour that settings cannot express goes in the client's extension package. Its
   `register(registry)` attaches functions to hooks that core declares, for example
   `payroll.employee_inputs`. Put the package's numbers under `[extension.settings]` in `client.toml`
   (text, whole numbers or true/false; money as quoted text) and read them with
   `settings.EMS_CLIENT.extension_settings`, so changing an amount never needs a code change.
4. Point the install at it with `EMS_CLIENT_CONFIG`.

`clients/_sample_workshop` is a worked example: no leave or overtime, a 26-day month, transport
exempt from tax, and an extension that pays a full-attendance bonus. `tests/test_sample_client.py`
and `tests/test_client_isolation_django.py` run the same employees through both clients to prove
that one core serves both and nothing leaks between them.

## Install for a client

```bash
cd deploy
cp .env.example .env        # set SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS
EMS_CLIENT_DIR=/path/to/client-repo docker compose up -d --build
```

Production refuses to start without a strong `SECRET_KEY`, `ALLOWED_HOSTS` and an explicit
`EMS_CLIENT_CONFIG`, or when the client enables a module that is not installed.
`/healthz` reports liveness and `/readyz` reports database connectivity.
