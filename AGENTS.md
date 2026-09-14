# AGENTS.md — grafana-integrations

Toolkit to manage Grafana dashboards as JSON: normalize datasource/metric
references, mirror a local folder tree to Grafana folders, and upload.

## Repo layout

| Path | Purpose |
|---|---|
| `src/commands/` | CLI subcommands: `check`, `discover`, `metrics`, `normalize`, `verify`, `upload` |
| `src/helpers/` | dashboard parsing, normalization rules/transforms |
| `src/core/` | settings, auth (`data/.env`), discovery state (`data/state/`) |
| `dashboards/tested/` | **Source of truth for uploads** (see below) |
| `dashboards/normalized/` | Output of `normalize` (not used by `upload-tested`) |
| `dashboards/{needs_fix,untested}/` | Staging / not part of the upload flow |
| `Justfile` | Task runner entry points |

## Justfile

```
just check              # verify Grafana connectivity/auth
just upload-tested      # upload dashboards/tested/, mirroring its folder tree
just upload-tested-dry  # dry-run: print folders + intended uploads
just normalize          # rewrite tested/ -> normalized/ (preserves nested tree)
just upload             # upload dashboards/normalized/
just pipeline           # discover -> metrics -> normalize -> verify -> upload
just clean              # remove generated files (normalized/, data/state/)
```

`upload-tested` is the command to use for our dashboards. It only reads
`dashboards/tested/`; ignore everything outside it. `normalize` preserves the
nested folder structure, so the `pipeline`/`upload` flow mirrors it too.

## Dashboard storage layout (tested/)

Dashboards are grouped into two top-level groups; **the local directory tree is
mirrored 1:1 as nested Grafana folders** on upload.

```
dashboards/tested/
  my-perfect-system/       # OUR curated dashboards (full standard)
    cluster/               # 1
    host/                  # 6  (tabbed: CPU, Disks, HwMon, Memory, Network, System)
    logs/                  # 8
    meta-monitoring/       # 3
  public/                  # third-party / imported dashboards (minimal changes)
    blackbox/              # 1
    docker/                # 6
    host/                  # 3
    meta-monitoring/       # 5
    sms/                   # 5
```

Categories are directories (e.g. `host`, `sms`). The **category slug** is the
relative folder path with `/` replaced by `-`: `my-perfect-system-host`,
`public-meta-monitoring`, etc.

---

## Standard: `my-perfect-system/*` (must stay uniform)

Every dashboard we create/curate MUST follow all of the rules below. These are
the invariants — "same colors, same theme, same rows/areas, same links, same
tags".

### 1. Colors / theme

- Stat panels use `options.colorMode: "background_solid"`.
- Base threshold colour (`fieldConfig.defaults.thresholds.steps[0].color`):
  - light: `#C7DBF5`
  - dark:  `#4B617F`
- `Statistics` and `Series` Overview stats alternate light/dark by visual
  order, **per grid line, in groups of 2**: `[L L][D D][L L][D D] ...`
  (8 per line → `LL DD LL DD`).
- `Summary` Overview stats are **all light** (`#C7DBF5`) — no dark steps.
- Existing alert steps (e.g. `orange`, `red`, `#EAB839`) are kept on top of the
  base colour — only the base step is themed.
- v2 dashboards keep the same colours under
  `spec.elements.*.spec.vizConfig.spec.options / fieldConfig`.

### 2. Rows / areas (section titles)

- `host` resources are **tabbed v2 dashboards** (see §8): tabs
  `Summary` / `Series` / `Statistics` (always in that order).
  - `Summary` tab: `Overview` (6 headline stats) → `Timeline` → `Top lists`
    (one row, exactly two panels). **No tables and no `Details` row**, and
    device-level panels are aggregated to the whole host.
  - `Series` tab: the detailed per-device/per-series view — `Overview` →
    `Thresholds` → domain/timeline rows (timeseries only beyond the Overview —
    no tables, piecharts, top-list bargauges or heatmaps; at most 2 panels per
    row).
  - `Statistics` tab: `Overview` → `Composition` → `Rankings` → `Inventory`.
- `logs`: `Overview` → `Timeline` → `Top lists` → `Details` → `Raw logs`
- `meta-monitoring`: `Overview` → `Timeline` → `Top lists` →
  `Content & users` → `Alerts & policies` → `Details`
- `cluster` (v2): tabs `Metrics` / `Logs` / `Monitoring`, each with
  `Overview` / `Timeline` / `Details` (+ domain rows such as
  `Prometheus` / `Loki` / `Grafana` in the Monitoring tab).
- Do **not** add a markdown/text "nav" panel. Navigation is done with native
  Grafana dashboard links (below).

### 3. Time & refresh

- `time`: `{"from": "now-5m", "to": "now"}` (v2: `spec.timeSettings`)
- `refresh`: `1m` (v2: `spec.timeSettings.autoRefresh = "1m"`)

### 4. Variables (keep them)

- `host`, `logs` and `cluster` have a `hostname` (label `Host`)
  query variable.
- `logs` family also has `search` (label `Search`); `sudo` adds an `ansible`
  custom variable.
- `meta-monitoring` currently has no variables (service-scoped dashboards).
- `host` resource dashboards add one filter variable per crowded
  label dimension (see §8), same shape as `hostname`: `query` type,
  `multi: true`, `includeAll: true`, default `All`, `sort: 1`, `refresh: 2`.
  Variable names are kept generic (`mode`, `cpu`, `device`, `mountpoint`,
  `chip`, `unit`) so `includeVars: true` on the links carries the selection.
  Boolean toggles use `SwitchVariable` (`idle` for CPU, `docker` for Network).
- Never remove existing variables. New dashboards should include at least the
  `hostname` query variable when the data supports it.

### 5. Tags

- Common tag on every dashboard we own: `my-perfect-system`.
- Per-folder category tag: `my-perfect-system-<category>` where `<category>` is
  the folder name (`cluster`, `host`, `logs`, `meta-monitoring`).
- Keep the descriptive tags that already exist (e.g. `cpu`, `node-exporter`,
  `loki`) — they are harmless.

### 6. Links (native Grafana dashboard links in the toolbar)

Use the `links` array (classic) / `spec.links` (v2). Link object shape:

```json
{
  "type": "dashboards",
  "title": "<Title>",
  "tags": ["<tag>"],
  "asDropdown": true,
  "icon": "dashboard",
  "includeVars": true,
  "keepTime": true,
  "targetBlank": false,
  "tooltip": "<Title> dashboards",
  "url": ""
}
```

Required links on **every** `my-perfect-system` dashboard, in order:

| Title | Tag |
|---|---|
| `My Perfect System` | `my-perfect-system` |
| `Host` | `my-perfect-system-host` |
| `Logs` | `my-perfect-system-logs` |
| `Meta-Monitoring` | `my-perfect-system-meta-monitoring` |

Do not add cross-category links between `cluster` and the others beyond the
above set. No self-referential link to `cluster`.

### 7. Titles

Resource dashboards are titled `CPU`, `Disks`, `HwMon`, `Memory`, `Network`,
`System` (all under `host/`); their tabs are always `Summary`,
`Series`, `Statistics` (see §8). Other titles: `Cluster Summary`, the
`<Topic> Log Analysis` log dashboards, and the `<Service> Metrics`
meta-monitoring dashboards.

### 8. Resource dashboards (tabbed — Summary / Series / Statistics)

Every `host` resource is **one v2 dashboard** with exactly **three
tabs**, always named `Summary`, `Series`, `Statistics` (in that order). The
former standalone `<Resource> - <Type>` and `<Resource> - Statistics`
dashboards were merged into these tabs and removed.

| Dashboard | File | uid | Series tab focus | Variables |
|---|---|---|---|---|
| `CPU` | `host/dashboard_cpu.json` | `cpu-metrics` | modes / cores | `hostname`, `mode`, `cpu`, `idle` |
| `Disks` | `host/dashboard_disk.json` | `disk-metrics` | filesystems / disks | `hostname`, `device`, `mountpoint` |
| `HwMon` | `host/dashboard_hwmon.json` | `hwmon-metrics` | chips / sensors | `hostname`, `chip` |
| `Memory` | `host/dashboard_memory.json` | `memory-metrics` | memory detail | `hostname` |
| `Network` | `host/dashboard_network.json` | `network-metrics` | interfaces | `hostname`, `device`, `docker` |
| `System` | `host/dashboard_system.json` | `system-metrics` | systemd units | `hostname`, `unit` |

Rules:

- `Summary` is the at-a-glance view for the selected host(s): only the most
  important headline stats, **no tables and no `Details` row**. `Overview` is
  **6 stats (3 per line × 2 lines, `w=8`, `h=4`, all light `#C7DBF5`)**, then
  `Timeline`, then `Top lists` (exactly one row with the two most important
  panels). Traffic/throughput/utilisation panels aggregate over the whole host
  (averages — e.g. `read`/`write`, `rx`/`tx`, `avg by (host)`) instead of
  listing individual devices.
- `Series` is the **detailed** crowded-dimension view. `Overview` is 8×2
  (`w=3`, `h=4`): line 1 counts, line 2 the matching percentages, each
  percentage sitting in the same column as its counterpart where one exists.
  Then a `Thresholds` row of gauges, then domain/timeline timeseries. Beyond
  the Overview it is **timeseries only** — no tables, piecharts, top-list
  bargauges or heatmaps; at most 2 panels per row. Per-device/per-series detail
  lives here.
- `Statistics` is the fleet-wide statistics view. `Overview` is 8×2: line 1
  counts/absolute values, line 2 percentages or per-second rates.
  `Composition` / `Rankings` / `Inventory` follow the recipe in §9.
- **Avoid repeating the same stat across the three tabs.** The `Summary` tab
  carries the headline stats, `Series` the crowded-dimension details and
  `Statistics` the fleet statistics. Where a resource exposes too few distinct
  countable metrics (e.g. `Disks`, `HwMon`) some overlap is unavoidable and
  accepted.
- Theme, tags, links, time/refresh follow the normal category standard.
- Label the correct metric family: `node_disk_*` → `device`, `node_filesystem_*`
  → `mountpoint` (its `device` label is `/dev/sdX1`, not the disk),
  `node_network_*` → `device`, `node_hwmon_*` → `chip`, `node_systemd_unit*` →
  `name` (surfaced as variable `unit`).

The `Series` tab is written for an admin hunting errors/problems and checking
performance: `Overview` stats carry counts/sums/percentages/instantaneous
readings, then a `Thresholds` row of gauges (themed base colour + `orange`/`red`
alert steps) carrying per-second rates, then raw timeseries details.

### 9. Statistics tab (fleet-wide statistics) — RECIPE

The `Statistics` tab of each resource dashboard (see §8), aimed at capacity /
ranking / composition questions across the whole fleet (`$hostname` defaults to
`All`). Unlike the `Series` tab these use exactly the panel types we avoid there:
**tables, piecharts, bargauges, forecasts**. This section is the recipe for the
`Statistics` tab of every resource dashboard — in particular the 16-stat
`Overview` with the matching percentage line and the 24h-average rankings.

Resources: `CPU` (`cpu-metrics`), `Disks` (`disk-metrics`), `HwMon`
(`hwmon-metrics`), `Memory` (`memory-metrics`), `Network` (`network-metrics`),
`System` (`system-metrics`).

#### 9.1 Rows (top to bottom)

1. **`Overview` — 2 grid lines × 8 stats (16 total).** Use fewer only when the
   resource truly lacks metrics.
   - **Line 1 = absolute / countable values.** Group all sum/byte values on the
     **left**, then counts to the right (e.g. `Raw capacity, Used, Free,
     Total inodes, Free inodes, Disks, Filesystems, Queue depth`).
   - **Line 2 = percentages**, each being the % counterpart of the stat
     **directly above it (same column)** (e.g. `Used capacity %, Used %,
     Free capacity %, Inode usage %, Free inode %, Active disks %, Full
     filesystems %, IO utilisation %`).
   - Colours: per line `LL DD LL DD` (`#C7DBF5` / `#4B617F`); keep existing
     `orange`/`red` alert steps. Exported JSON may render the base step as
     `{"value": 0}` instead of `{"value": null}` — that is fine.
2. **`Composition` — 4 piecharts in one grid line** (`w=6`, `h=8` each), broken
   down by the resource's device/dimension (mode/core/device/mountpoint/fstype/
   node/chip/state/type) — **never by host**.
3. **`Rankings` — a bargauge (top-N devices) plus a table**, both grouped by the
   device/dimension.
4. **`Inventory` / `Forecast` — tables**: per-device inventory, error lists, or
   `predict_linear` capacity forecasts.

#### 9.2 Cross-cutting rules

- Carry the **same filter variable(s) as the `Series` tab** (`mode`/`cpu`,
  `device`/`mountpoint`, `device`, `chip`, `unit`) and scope every query with it.
- **Group by the device/dimension — never by host** (host-scoped groupings break
  when a single host is selected).
- Theme, tags, links, time/refresh follow the normal category standard; the
  required `Host` link is present on every dashboard.

#### 9.3 Ranking/table aggregation window (24h averages)

For "steady-state" rankings and tables prefer an average over a rolling window by
widening the PromQL range selector — `rate` over a long window already averages:

```
rate(node_disk_reads_completed_total{…}[24h])   # average per-second rate over 24h
```

Example: `Devices by IOPS (24h avg)` is
`sort_desc(topk(10, sum by (device) (rate(node_disk_reads_completed_total{…}[24h]) + rate(node_disk_writes_completed_total{…}[24h]))))`.
Do **not** wrap it in a subquery; `[24h]` is enough.

#### 9.4 Multi-column table recipe (important)

Prometheus instant queries return **one frame per series**, so a plain
multi-query table renders long (`Value #A`, `Value #B`, …) and `joinByField`
cannot merge the frames. Build wide tables like this every time:

1. **One instant query per column**, `format: table`, and name the value field in
   PromQL so it is unique (otherwise every column is called `Value`):
   ```
   label_replace(<agg expr>, "__name__", "<colname>", "__name__", ".*")
   ```
2. **Panel transformations, in order:**
   1. `labelsToFields` `{ "mode": "columns" }` — labels become columns.
   2. `organize` `{ "excludeByName": { "__name__": true, "Time": true } }` — drop
      the `__name__` label and `Time` so rows from different queries share the
      same key.
   3. `merge` `{}` — align rows on the common label set; each uniquely-named
      value field becomes its own column.
   4. `organize` — final order + friendly names, e.g.
      `indexByName: { host:0, mountpoint:1, fstype:2, capacity:3, used:4, free:5, … }`,
      `renameByName: { mps_alloy_hostname: "host", … }`.
3. Set `fieldConfig.defaults.unit` for the numeric columns and add `byName`
   overrides for percentage columns (`unit: percent`).

**Pitfalls that make this fail (do not skip):**
- `merge` keys on **all columns common to the frames** — drop `Time` and any
  per-query-only label (e.g. a synthetic `kind`), or rows never align.
- If the value fields are all named `Value`, `merge` collapses them into one
  column — hence the `label_replace(__name__)` step.
- `joinByField` is **not** usable for Prometheus multi-series instant queries
  (one frame per series, same `refId`).

Example (Disks `Forecast` table) → `host · mountpoint · fstype · capacity · used
· free · used % · used in 24h · used % in 24h`, with columns derived by
`capacity/size`, `used = size - avail`, `free = avail`, `used_pct = 100·used/size`,
`used_24h = size - predict_linear(avail[6h], 24h)`, `used_pct_24h`.

**Alternative (pivot) recipe — used for the rankings/inventory tables.** When the
merge recipe collapses (each `labelsToFields` value field is renamed `Value`),
build the wide table from a single query instead:

1. One instant query, `format: table`, joining per-column terms with `or`; tag
   each term with a synthetic `metric` label via
   `label_replace(<agg>, "metric", "<col>", "__name__", ".*")`.
2. Transformations: `labelsToFields` (`mode: columns`) → `groupingToMatrix`
   (`rowField` / `columnField` / `valueField: "Value"`) → `organize`
   (order + friendly names) → `sortBy` as needed.
3. To keep two key columns (e.g. `host` and `interface`) build a combined label
   with `label_join(<agg>, "iface", " ", "mps_alloy_hostname", "device")`, pivot
   on it, then split it back with an `extractFields` transformation
   (`format: regexp`, `regExp: "/(?<host>[^ ]+) (?<interface>.+)/"`).

#### 9.5 Layout algorithm (when generating/regenerating)

- stats wrap at **8 per grid line** (`w=3`, `h=4`); gauges `w=24/n`;
  piecharts **4 per line** (`w=6`, `h=8`); timeseries/other panels at most
  **2 per line** (`w=12`, or `w=24` when alone).
- Single-query label/value tables standardize on `labelsToFields` + `organize`
  (drop `Time`, `__name__`, `job`, `instance`, `mps_alloy_*`).

#### 9.6 Format

All resource dashboards are **v2** (`apiVersion: dashboard.grafana.app/v2`,
`kind: Dashboard`, `spec.*`) with a top-level `TabsLayout`; each tab holds a
`RowsLayout`. `just upload-tested` strips v2 server metadata on upload.

---

## Standard: `public/*` (third-party — minimal changes)

These are imported/downloaded dashboards. We only add navigation metadata; we do
**not** restyle them.

- Do **not** change their theme, rows, panels, queries, variables, time or
  refresh.
- Add the `public` tag (already present) plus one category tag
  `public-<category>` (`blackbox`, `docker`, `host`, `meta-monitoring`, `sms`).
- Add exactly one native dashboard link: their own category
  (e.g. SMS dashboard → `SMS` link with tag `public-sms`).
- Do **not** add a `My Perfect System` link and do **not** add the
  `my-perfect-system` tag to public dashboards.

---

## Upload behaviour (`src/commands/upload.py`)

The upload command (`just upload-tested` and `just upload`) runs two phases:

1. **Pre-create the folder tree.** Walks the local source dirs and ensures each
   mirrored path exists remotely (parents first via `parentUid`), then keeps the
   `{folder_path: uid}` map. Prints `folders created (...)`.
2. **Upload.** Each dashboard goes into its pre-resolved `folderUid`. Before
   sending it:
   - resolves datasource aliases (`${DS_PROMETHEUS}`, `${DS_LOKI}`, …) from
     `data/state/datasources.json` — never hardcode datasource UIDs;
   - strips server metadata from v2 docs (`clean_v2_metadata`);
   - assigns a deterministic uid to classic dashboards that have none
     (`uuid5(NAMESPACE_DNS, "<folder>/<file>")`);
   - reassigns duplicate uids deterministically so two files don't overwrite
     each other.

Options: `--source <dir>` (default `dashboards/normalized/`), `--all`,
`--folder <sub>`, `--file <path>`, `--dry-run`, `--namespace`.

Two flows, both mirroring the tree: `upload-tested` reads `dashboards/tested/`;
`upload` / `pipeline` reads `dashboards/normalized/`, which `normalize` writes
with the full relative folder path (see `dashboard.load_dashboards`).

> When you rename/move a folder, also update the dashboard's category tag and
> link (folder path drives the generated uid for uid-less files). Otherwise the
> old folder can keep a stale duplicate — run the upload, check for empty
> folders, and remove them.

---

## Adding / changing a dashboard

1. Put the JSON under the correct `dashboards/tested/<group>/<category>/`.
2. Apply the group standard above (theme, rows, time, refresh, tags, links).
3. `just upload-tested-dry` — confirm the mirrored folder path and edits.
4. `just upload-tested` — upload.
5. Verify live (folder, tags, links, variables).

## Ground rules

- Keep `my-perfect-system/*` visually and structurally identical to each other.
- Keep `public/*` untouched except for its category tag + single link.
- Navigation is native Grafana links, not markdown panels.
- Never commit `data/.env` (git-ignored); never hardcode datasource UIDs.
- `uploads` are idempotent — re-running `just upload-tested` is safe.
