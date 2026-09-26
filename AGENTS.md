# AGENTS.md — grafana-integrations

Toolkit to manage Grafana dashboards as JSON: normalize datasource/metric
references, mirror a local folder tree to Grafana folders, and upload.

## Repo layout

| Path | Purpose |
|---|---|
| `src/commands/` | CLI subcommands: `check`, `discover`, `metrics`, `normalize`, `verify`, `upload`, `upload-alerts` |
| `src/helpers/` | dashboard parsing, normalization rules/transforms |
| `src/core/` | settings, auth (`data/.env`), discovery state (`data/state/`) |
| `dashboards/tested/` | **Source of truth for uploads** (see below) |
| `dashboards/normalized/` | Output of `normalize` (not used by `upload-tested`) |
| `dashboards/{needs_fix,untested}/` | Staging / not part of the upload flow |
| `alerts/` | **Source of truth for alert rule groups** (see below) |
| `Justfile` | Task runner entry points |

## Justfile

```
just check              # verify Grafana connectivity/auth
just upload-tested      # upload dashboards/tested/, mirroring its folder tree
just upload-tested-dry  # dry-run: print folders + intended uploads
just upload-alerts      # upload alert rule groups from alerts/
just upload-alerts-dry  # dry-run: print groups/rules + folders
just normalize          # rewrite tested/ -> normalized/ (preserves nested tree)
just upload             # upload dashboards/normalized/
just pipeline           # discover -> metrics -> normalize -> verify -> upload
just clean              # remove generated files (normalized/, data/state/)
```

`upload-tested` is the command to use for our dashboards. It only reads
`dashboards/tested/`; ignore everything outside it. `normalize` preserves the
nested folder structure, so the `pipeline`/`upload` flow mirrors it too.

## Alerts (`alerts/`)

`alerts/` is the source of truth for Grafana-managed alert rules. **One JSON
file = one rule group** in the Grafana Alerting provisioning format. Alert
rules are consolidated into **rule groups** under the `alerts/` Grafana root
(kept separate from dashboard folders so alert folders don't appear as empty
dashboard folders): `alerts/my-perfect-system/clusters/<cluster>` for cluster-
scoped groups (all cluster-level groups — `cluster_health`,
`host_meta`, `cluster_recordings`, `services_ollama`, `services_sms`, `services_blackbox`, `services_docker`, `host_logs`, `host_metrics` — sit directly at
the cluster level), plus `alerts/my-perfect-system/meta` (one group per
monitoring backend service).
A rule's
`uid`/`title` reflects its path:
`<clustername>_<rulegroup>_<feature>` (e.g. `tortuga_host_metrics_down`).

```
alerts/
  my-perfect-system/
    clusters/
      tortuga/
        cluster_health.json     # group "cluster_health"     (view: cluster)
        host_meta.json          # group "host_meta"          (view: meta, alloy)
        cluster_recordings.json # group "cluster_recordings" (recording rules)
        services_ollama.json  # group "services_ollama"  (view: service)
        services_sms.json  # group "services_sms"  (view: service)
        services_blackbox.json  # group "services_blackbox"  (view: service)
        services_docker.json  # group "services_docker"  (view: service)
        host_logs.json      # group "host_logs"    (view: host, Loki)
        host_metrics.json   # group "host_metrics" (view: host)
    meta/
      prometheus.json     # group "prometheus" (view: meta)
      loki.json           # group "loki"       (view: meta)
      grafana.json        # group "grafana"    (view: meta)
```

| File | Group | `view` | Covers |
|---|---|---|---|
| `clusters/tortuga/cluster_health.json` | `cluster_health` | `cluster` | cluster `tortuga` liveness: `cluster not reporting` alert |
| `clusters/tortuga/host_meta.json` | `host_meta` | `meta` | monitoring exporter self-scrape (alloy) |
| `clusters/tortuga/cluster_recordings.json` | `cluster_recordings` | — | the cluster's recording rules (`mps_sensor_excluded`, `mps_tortuga_host_expected`) |
| `clusters/tortuga/services_ollama.json` | `services_ollama` | `service` | service liveness (ollama) |
| `clusters/tortuga/services_sms.json` | `services_sms` | `service` | SMS exporter self-checks + service liveness (openvpn server/client, reboot, packages) |
| `clusters/tortuga/services_blackbox.json` | `services_blackbox` | `service` | blackbox probe down + TLS cert expiry (invalid, 3d, 7d) |
| `clusters/tortuga/services_docker.json` | `services_docker` | `service` | Docker/cAdvisor down + container OOM kill + restart loop |
| `clusters/tortuga/host_metrics.json` | `host_metrics` | `host` | per-host health (down, disk, inodes, swap, OOM, systemd, temp, fan) |
| `clusters/tortuga/host_logs.json` | `host_logs` | `host` | Loki log events (root SSH login, sudo misuse, SSH brute force, fail2ban bans, kernel panic/oops, cron failures, docker errors) |
| `meta/prometheus.json` | `prometheus` | `meta` | prometheus self-checks (down, TSDB compaction/WAL failures) |
| `meta/loki.json` | `loki` | `meta` | loki self-checks (down, panics, WAL disk-full, flush failures) |
| `meta/grafana.json` | `grafana` | `meta` | grafana self-checks (down, invalid alerts, notification write failures) |

### Labels

Every rule carries a `view` label for filtering in the Alerting UI:

| `view` | meaning |
|---|---|
| `host` | per-host state (`host_metrics`, `host_logs`) |
| `cluster` | cluster-wide state (`cluster_health`) |
| `service` | service liveness (`services_ollama`, `services_sms`, `services_blackbox`, `services_docker`) |
| `meta` | monitoring-stack self-checks (`host_meta`, `prometheus`, `loki`, `grafana`) |

Cluster-scoped rules also carry a `cluster` label (value = cluster name, e.g.
`tortuga`); service-liveness rules carry `service`; every rule carries
`severity` (`critical` / `warning`).

### Recording rules

Static metadata lives as recording rules (metric prefix `mps_`), consolidated
in the cluster's `cluster_recordings` group rather than inline in queries:

| Metric | Labels | Group | Meaning |
|---|---|---|---|
| `mps_sensor_excluded` | `chip`, `sensor` | `cluster_recordings` | known false-positive hardware sensors |
| `mps_tortuga_host_expected` | `mps_alloy_hostname` | `cluster_recordings` | expected hosts for cluster `tortuga` |

Recording rules use a `record` block instead of `condition` and write into
Prometheus via `record.target_datasource_uid: "${DS_PROMETHEUS}"`. To change a
list (exceptions, expected hosts) edit the `cluster_recordings` group file and
re-upload — never inline the list in queries.

### noDataState

Down-detection rules (`up == 0`) use `"noDataState": "NoData"`. Rules whose
absence is normal — counter/threshold checks, sensor alarms — use
`"noDataState": "OK"` (the `*-down` rule covers the service/host-out case).

### Notification routing

Routing lives in Grafana's **notification policies**, not in these files. We keep
it simple: one policy whose routes match both integrations (email and Telegram),
so every firing alert goes to both contact points immediately. There is **no
time-based escalation** (`for`/`after`/"still firing after N hours") in Grafana
policies — the routing tree only matches on **labels** and **mute timings**;
`group_wait`/`group_interval`/`repeat_interval` re-notify the *same* receiver,
they never switch receivers after a delay. Do not try to express "email now,
Telegram in 3 days" in routing; if that split is ever wanted it must be done at
rule level (twin rules with a longer `for` + a routing label).

### Format

```json
{
  "folder": "alerts/my-perfect-system/clusters/tortuga",
  "orgId": 1,
  "title": "cluster_health",
  "interval": 60,
  "rules": [
    {
      "uid": "tortuga_cluster_health_hosts_up",
      "title": "tortuga_cluster_health_hosts_up",
      "condition": "C",
      "for": "5m",
      "noDataState": "OK",
      "execErrState": "Error",
      "labels": { "severity": "critical", "cluster": "tortuga", "view": "cluster" },
      "annotations": { "summary": "…", "description": "…" },
      "data": [ { "refId": "A", "…": "query" }, { "refId": "C", "…": "classic_conditions" } ]
    }
  ]
}
```

Recording rules live in their own `cluster_recordings` group, one per cluster:

```json
{
  "folder": "alerts/my-perfect-system/clusters/tortuga",
  "orgId": 1,
  "title": "cluster_recordings",
  "interval": 60,
  "rules": [
    {
      "uid": "tortuga_cluster_recordings_host_expected",
      "title": "tortuga_cluster_recordings_host_expected",
      "record": { "metric": "mps_tortuga_host_expected", "from": "A", "target_datasource_uid": "${DS_PROMETHEUS}" },
      "for": "0s",
      "isPaused": false,
      "data": [ { "refId": "A", "…": "query" } ]
    }
  ]
}
```

- `folder` is a Grafana folder **path** under the `alerts/` root (created/mirrored
  like dashboard folders, but kept under `alerts/` so alert folders are separate
  from dashboard folders); use `folderUid` to target a folder directly. All
  groups live under `alerts/my-perfect-system/`: a cluster's groups directly in
  `"folder": "alerts/my-perfect-system/clusters/<cluster>"` (e.g.
  `clusters/tortuga`, with groups `cluster_health`, `host_meta`, `cluster_recordings`, `services_ollama`,
  `services_sms`, `services_blackbox`, `services_docker`, `host_logs`, `host_metrics`), or `"folder": "alerts/my-perfect-system/meta"` for the
  backend self-checks. Rule uids/titles encode the path as
  `<clustername>_<rulegroup>_<feature>` (e.g.
  `tortuga_cluster_health_hosts_up`, `tortuga_host_meta_target_down`,
  `tortuga_host_metrics_down`), and metrics carry the `mps_` prefix
  (`mps_tortuga_host_expected`, …).
- `data[].datasourceUid` and `record.target_datasource_uid` use aliases
  (`${DS_PROMETHEUS}`, `${DS_LOKI}`), resolved from
  `data/state/datasources.json`; `__expr__` is left untouched.
- Upload with `just upload-alerts` (`src/commands/upload_alerts.py`). It is
  idempotent: each group is upserted via
  `PUT /api/v1/provisioning/folder/{folderUid}/rule-groups/{group}`, so the
  local file is the source of truth for that group. Rules move by `uid`, so
  renaming/relocating a group is just a file edit + re-upload (no manual
  deletion needed). Uploads send `X-Disable-Provenance: true` so rules stay
  editable in the Grafana UI (provenance is not set).

## Dashboard storage layout (tested/)

Dashboards are grouped into two top-level groups; **the local directory tree is
mirrored 1:1 as nested Grafana folders** on upload.

```
dashboards/tested/
  my-perfect-system/       # OUR curated dashboards (full standard)
    cluster/               # 1
    host/                  # 6  (tabbed: CPU, Disks, HwMon, Memory, Network, System)
    logs/                  # 8
    meta/                  # 5  (tabbed v2: Prometheus, Loki, Grafana, Alloy + Alerts)
    services/              # 3  (tabbed v2: Ollama Metrics, Llama.cpp Metrics, GPU (AMD))
  public/                  # third-party / imported dashboards (minimal changes)
    blackbox/              # 1
    docker/                # 6
    host/                  # 3
    meta/                  # 5
    sms/                   # 5
```

Categories are directories (e.g. `host`, `sms`). The **category slug** is the
relative folder path with `/` replaced by `-`: `my-perfect-system-host`,
`public-meta`, etc.

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
- `meta` (v2, tabbed — Performance template, see §10): tabs `Overview` /
  `Health` / `Stats` / `Averages` / `Scrape` / domain tabs (see §10)
- `cluster` (v2): tabs `Metrics` / `Logs` / `Monitoring`, each with
  `Overview` / `Timeline` / `Details` (+ domain rows such as
  `Prometheus` / `Loki` / `Grafana` in the Monitoring tab).
- `services` (v2, tabbed): service-specific tabs, flat — no row
  sub-categories (create separate tabs instead), with series panels
  arranged two per line (`w=12`, 2x2-style grids; a lone panel takes the
  full width). `GPU (AMD)`
  uses tabs `Overview` (stats only: 16 instant + 8 24h stats) / `Utilization`
  (utilization series + 1h-average trend + GFX/memory clocks) /
  `Power & temperatures` / `Media` / `Memory & PCIe` / `Health` / `Stats`
  (current-composition piecharts, 24h time-share bargauges + per-GPU
  inventory table). Its stat
  panels copy the Ollama style (`colorMode: value` + percent change with
  semantic red/orange/green thresholds; only the up stat is
  `background_solid` red/green) instead of the themed base colours.
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
- `meta` currently has no variables (service-scoped dashboards).
- `services` dashboards scope by their own dimension: `GPU (AMD)` has
  `hostname` + `gpu` (per-GPU filter, same shape as `hostname`);
  `Ollama Metrics` has `model`.
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
  the folder name (`cluster`, `host`, `logs`, `meta`, `services`).
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
| `Meta` | `my-perfect-system-meta` |

Do not add cross-category links between `cluster` and the others beyond the
above set. No self-referential link to `cluster`.

### 7. Titles

Resource dashboards are titled `CPU`, `Disks`, `HwMon`, `Memory`, `Network`,
`System` (all under `host/`); their tabs are always `Summary`,
`Series`, `Statistics` (see §8). Other titles: `Cluster Summary`, the
`<Topic> Log Analysis` log dashboards, the `<Service> Metrics` service
dashboards plus `GPU (AMD)` (`my-perfect-system/services/`), and the meta
dashboards `Prometheus`, `Loki`, `Grafana`, `Alloy` and the cross-service
`Alerts` dashboard (`my-perfect-system/meta/`, rows `Overview` → `Timeline` →
`Groups` → `Alert rules`; its centerpiece is the native **Alert list** panel —
the `datasource` plugin has no alert query type in Grafana 13, so per-rule
alert tables must use `alertlist`, which needs no datasource reference).

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

## Standard: `meta/*` (Performance template) — §10

The meta dashboards are **one consolidated tabbed v2 dashboard per monitoring
backend service**, built on the Performance template (the former per-service
base + performance dashboard pairs were merged into these and removed).

| Dashboard | File | uid (`metadata.name`) | Tabs |
|---|---|---|---|
| `Prometheus` | `meta/dashboard_prometheus.json` | `meta-prometheus` | Overview / Health / Stats / Compositions / Details / Averages / Scrape / Ingest / Head & Series / Storage & Compaction / Query & API / Jobs & Targets |
| `Loki` | `meta/dashboard_loki.json` | `meta-loki` | Overview / Health / Stats / Compositions / Details / Averages / Scrape / Streams & Labels / Throughput / Chunks & Flush / Query & Ring |
| `Grafana` | `meta/dashboard_grafana.json` | `meta-grafana` | Overview / Health / Stats / Compositions / Details / Averages / Scrape / HTTP & API / Datasource / Users & Auth / Content & Inventory |
| `Alloy` | `meta/dashboard_alloy.json` | `meta-alloy` | Overview / Health / Details / Averages / Scrape / Components |
| `Alerts` | `meta/dashboard_alerts.json` | `alerts-metrics` | (cross-service, own layout — see §7) |

### 10.1 Tab recipes

- **`Overview`** — stat panels sit **directly in the tab root** (no section
  headers); **exactly 6 stat panels per grid line** (`w=4`, `h=3`, instant
  queries). Ordering is by importance and category, without labels: the
  `<Service> Up` panel is top-left, followed by `Total alerts` and
  `Firing alerts` (per-component alert counts — `Total alerts` is a native
  stat counting the alert rules in the component's Grafana rule group via
  `grafana_alerting_rule_group_rules{rule_group=~".*;<group>"`;   `Firing
  alerts` is a native stat counting
  `count(count_over_time(GRAFANA_ALERTS{view="meta", service=<svc>,
  grafana_alertstate="alerting"}[$__range]))` — coupled to the user's
  chosen dashboard range (Grafana writes
  `GRAFANA_ALERTS` on alert state transitions via
  `[unified_alerting.state_history]` backend=prometheus, which requires the
  datasource's `prometheusType: "Prometheus"` and the Prometheus
  remote-write receiver), then the other "something is
  off" panels (error/failure counters, alert state), then the remaining
  stats grouped by category in reading order.
- **`Averages`** — the headline rates averaged over the dashboard range, as
  timeseries arranged **three per line** (`w=8`, `h=9`; a lone panel takes
  the full width): rate-based stats derive
  their query from the Overview stat with `[5m]` widened to `[$__range]`
  (`sum(rate(...[$__range]))`); gauge stats become
  `avg(avg_over_time(<metric>{...}[$__range]))` — wrapped in `avg(...)` so
  every Averages panel is exactly **one series** even when the metric exports
  several (per instance/host). Title suffix `… avg`; the panel
  unit is copied from the source stat.
- **`Compositions`** — the piecharts (one row, legend docked `bottom` so long
  label names wrap and the value/percent columns stay visible).
- **`Details`** — the full-width tables (`Scrape health per job`, …), with
  the **`Build info` table always last** (very bottom of the Details page).
- **`Stats`** — **toplist | table pairs**:
  every row is a toplist (bargauge) on the **left** (`w=12`, `h=9`) and its
  table on the **right** — an existing matching table where available,
  otherwise a table twin of the same ranking.
- **Domain tabs** — the service's detailed timeseries, 2 per line
  (`w=12`, `h=8`); a lone panel takes the full width. Grid heights are
  integers (fractional heights are rejected by the API).
- **Tab order** — `Overview` / `Health` / `Stats` / `Averages` / `Scrape` /
  remaining domain tabs. `Health` is the service's health tab (Prometheus and
  Loki: the former `WAL & Health`; Grafana: the former `Alerting & Health`;
  Alloy: `Up`, `Config Load OK`, `Config Failures/s`). The `<Service> Up`
  series (e.g. `Prometheus Up`, `Loki Up`) is always the **top-left panel**
  of the Health tab.
- **Scrape panels** — the scrape-specific panels (`Samples per scrape`,
  `Scrape issues`, `Scrape duration`) make up the `Scrape` tab. On Prometheus
  the ingest rate series (`Samples/s`, `Exemplars/s`, `Scrapes/s`,
  `New series added (1h)`) live in a separate `Ingest` tab directly after
  `Scrape`.

### 10.2 Cross-cutting rules

- Theme, tags (`<service>` + `my-perfect-system` + `meta-monitoring` +
  `my-perfect-system-meta`), the 4 standard links, time `now-6h` → `now`,
  refresh `1m` (the Performance family deviates from §3 on purpose).
- Datasource alias `${DS_PROMETHEUS}` for every backend service.
- Job labels are ground truth from the alert rules: `prometheus`,
  `monitoring-loki`, `monitoring-grafana`;
  Alloy queries use `job="integrations/self"`.
- **Series colours** — every timeseries panel uses `palette-classic` (never
  threshold/continuous colouring, which paints whole panels green or red).
  Query colours are pinned **per panel** via `byFrameRefID` overrides:
  first query `green` (#73BF69), second `yellow` (#FADE2A), third `blue`
  (#5794F2), fourth `red` (#F2495C). This applies to all multi-query panels
  (including templated legends) and to single-series single-query panels.
  Single-query panels with dynamic grouped series (e.g. `by (job)`) stay on
  the plain palette (first line green, second yellow).
- **Overview stat style** — Overview stats use `options.colorMode: "value"`
  with a green base threshold step (existing alert steps kept on top); the
  themed `background_solid` base colours of §1 are not used on the meta
  Performance template. Every stat shows the **percent change**
  (`showPercentChange: true`, `percentChangeColorMode: "standard"`) and uses
  a uniform value font size (`text.valueSize: 25`).
- Depth lives as tabs: per-target/per-component detail in the domain tabs,
  service-level in `Overview`/`Averages`/`Stats`; the stack-level summary
  lives in `Cluster Summary` → `Monitoring`.

---

## Standard: `public/*` (third-party — minimal changes)

These are imported/downloaded dashboards. We only add navigation metadata; we do
**not** restyle them.

- Do **not** change their theme, rows, panels, queries, variables, time or
  refresh.
- Add the `public` tag (already present) plus one category tag
  `public-<category>` (`blackbox`, `docker`, `host`, `meta`, `sms`).
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
