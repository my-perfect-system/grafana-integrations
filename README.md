# grafana-integrations

Manage Grafana dashboards as code: keep them as JSON in this repo, normalize
their datasource/metric references, and upload them while **mirroring the local
folder tree** into Grafana (nested) folders.

- Dashboards live under `dashboards/tested/` (source of truth for uploads).
- The upload command resolves datasource placeholders, assigns stable UIDs, and
  recreates the folder hierarchy on the instance.
- Folder/dashboard conventions (colors, rows, links, tags) are documented in
  [`AGENTS.md`](AGENTS.md).

## Requirements

- Python 3 + `venv`
- [`just`](https://github.com/casey/just) (task runner)
- A Grafana instance and a **service account token** with datasource + dashboard
  permissions

## Setup

```bash
just setup                    # create .venv and install requirements.txt
cp data/.env.example data/.env
$EDITOR data/.env             # set GRAFANA_URL and GRAFANA_TOKEN
just check                    # verify connectivity / auth
```

`data/.env` is git-ignored. Environment variables override the file, so you can
also export `GRAFANA_URL` / `GRAFANA_TOKEN` (and optionally
`GRAFANA_VERIFY_SSL=false`, `GRAFANA_CA_CERT=/path/to/ca.pem`).

## Commands

| Command | Description |
|---|---|
| `just check` | Test connectivity and authentication |
| `just discover` | Fetch datasources/folders/version → `data/state/datasources.json` |
| `just metrics` | Fetch available metric names → `data/state/metrics.json` |
| `just normalize` | Rewrite dashboards into `dashboards/normalized/` (mirrors the `tested/` tree; datasource + metric replacements, cleanup) |
| `just normalize-dry` | Same, without writing files |
| `just verify` | Cross-check normalized dashboards against the instance snapshots |
| `just upload-tested` | **Upload `dashboards/tested/`, mirroring its folder tree** |
| `just upload-tested-dry` | Dry-run: print folders + intended uploads, no writes |
| `just upload` | Upload `dashboards/normalized/` (the normalize-based flow) |
| `just clean` | Remove generated files (`dashboards/normalized/`, `data/state/`) |
| `just pipeline` | `discover → metrics → normalize → verify → upload` (mirrors the folder tree) |

The same commands are available directly:

```bash
python -m src upload --all --source dashboards/tested
```

Useful `upload` options: `--all`, `--folder <sub>`, `--file <path>`,
`--source <dir>`, `--dry-run`, `--namespace <ns>`.

## Workflows

Both upload flows mirror the local folder tree into nested Grafana folders:

- **Direct** — `just upload-tested` uploads `dashboards/tested/` as-is and
  resolves datasource placeholders at upload time.
- **Normalized** — `just pipeline` (or `just normalize` then `just upload`)
  first rewrites dashboards into `dashboards/normalized/` (datasource + metric
  replacements, cleanup) and uploads that tree. `normalize` preserves the nested
  folder structure, so the normalized tree mirrors `dashboards/tested/`.

`just clean` removes the generated `dashboards/normalized/` and `data/state/`;
run `just discover` (and `just metrics`) again before the next upload.

## Dashboard layout

```
dashboards/tested/
  my-perfect-system/       # our curated dashboards (full standard)
    cluster/  hardware/  host/  logs/  meta-monitoring/
  public/                  # third-party/imported dashboards (minimal changes)
    blackbox/  docker/  host/  meta-monitoring/  sms/
```

Directories are categories. On upload, the path relative to
`dashboards/tested/` becomes the Grafana folder path — e.g.
`my-perfect-system/hardware/dashboard_cpu.json` lands in the nested Grafana
folder `my-perfect-system` → `hardware`. Empty/legacy folders are left for you
to clean up.

## Upload behaviour

The upload command (`just upload-tested` and `just upload`) runs in two phases:

1. **Pre-create the folder tree** — ensures every local directory exists
   remotely (parents first via `parentUid`) and builds a `{path: uid}` map.
2. **Upload** — each dashboard goes into its pre-resolved folder. Before
   sending, it:
   - resolves datasource aliases (`${DS_PROMETHEUS}`, `${DS_LOKI}`, …) from
     `data/state/datasources.json`;
   - strips server-side metadata from v2 dashboards;
   - assigns a deterministic UID to classic dashboards without one;
   - reassigns duplicate UIDs so files don't overwrite each other.

Uploads are idempotent — re-running `just upload-tested` is safe.

## Conventions

All dashboards we own (`my-perfect-system/*`) must keep the same theme, rows,
time/refresh, tags and native links; `public/*` dashboards only get a category
tag and a single own-category link. The full standard is in
[`AGENTS.md`](AGENTS.md).

## Repo layout

| Path | Purpose |
|---|---|
| `src/commands/` | CLI subcommands |
| `src/helpers/` | dashboard parsing, normalization rules/transforms |
| `src/core/` | settings, auth, discovery state |
| `dashboards/tested/` | source of truth for `upload-tested` |
| `dashboards/normalized/` | output of `normalize` (git-ignored) |
| `data/state/` | discovery/metrics snapshots (git-ignored) |
| `Justfile` | task runner entry points |
