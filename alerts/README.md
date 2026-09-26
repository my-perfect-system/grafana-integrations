# alerts/

Local store for Grafana alert rule groups (Grafana Alerting provisioning
format). Each JSON file describes **one rule group**; the folder tree mirrors
Grafana folders under the `alerts/` **root** (alerts are kept separate from
dashboard folders so they don't show up as empty folders in the dashboard
view).

```
alerts/
  my-perfect-system/
    clusters/
      tortuga/
        cluster_health.json     # group "cluster_health"     (view: cluster, label cluster: tortuga)
        host_meta.json          # group "host_meta"          (view: meta) — alloy self-scrape
        cluster_recordings.json # group "cluster_recordings" (recording rules)
        services_ollama.json  # group "services_ollama"  (view: service)
        services_sms.json  # group "services_sms"  (view: service)
        services_blackbox.json  # group "services_blackbox"  (view: service)
        services_docker.json  # group "services_docker"  (view: service)
        host_logs.json     # group "host_logs"   (view: host, Loki log events)
        host_metrics.json  # group "host_metrics" (view: host)
    meta/
      prometheus.json    # group "prometheus"  (view: meta)
      loki.json          # group "loki"        (view: meta)
      grafana.json       # group "grafana"     (view: meta)
```

Alert rules are consolidated into rule groups — views on the alarms. The
`clusters` folder nests by cluster (`tortuga`). A cluster's groups all sit
directly at the cluster level:

| Folder | Group | `view` label | Covers |
|---|---|---|---|
| `alerts/my-perfect-system/clusters/tortuga` | `cluster_health` | `cluster` | cluster-wide for cluster `tortuga`: the cluster-not-reporting alert |
| `alerts/my-perfect-system/clusters/tortuga` | `host_meta` | `meta` | monitoring exporter (alloy) |
| `alerts/my-perfect-system/clusters/tortuga` | `cluster_recordings` | — | the cluster's recording rules (`mps_sensor_excluded`, `mps_tortuga_host_expected`) |
| `alerts/my-perfect-system/clusters/tortuga` | `services_ollama` | `service` | service liveness (ollama) |
| `alerts/my-perfect-system/clusters/tortuga` | `services_sms` | `service` | SMS exporter self-checks + service liveness (openvpn server/client, reboot, packages) |
| `alerts/my-perfect-system/clusters/tortuga` | `services_blackbox` | `service` | blackbox probe down + TLS cert expiry (invalid, 3d, 7d) |
| `alerts/my-perfect-system/clusters/tortuga` | `services_docker` | `service` | Docker/cAdvisor down + container OOM kill + restart loop |
| `alerts/my-perfect-system/clusters/tortuga` | `host_metrics` | `host` | per-host health (down, disk, inodes, swap, OOM, systemd, temp, fan) |
| `alerts/my-perfect-system/clusters/tortuga` | `host_logs` | `host` | Loki log events (root SSH login, sudo misuse, SSH brute force, fail2ban bans, kernel panic/oops, cron failures, docker errors) |
| `alerts/my-perfect-system/meta` | `prometheus` | `meta` | monitoring backend (prometheus) |
| `alerts/my-perfect-system/meta` | `loki` | `meta` | monitoring backend (loki) |
| `alerts/my-perfect-system/meta` | `grafana` | `meta` | monitoring backend (grafana) |

Each rule also carries a `view` label (`host` / `cluster` / `service` / `meta`)
and cluster-scoped rules carry a `cluster` label (e.g. `cluster: tortuga`), so the
Alerting UI can filter across views and clusters independent of group/folder.

## File format

```json
{
  "folder": "alerts/my-perfect-system/clusters/tortuga",
  "orgId": 1,
  "title": "host_meta",
  "interval": 60,
  "rules": [
    {
      "uid": "tortuga_host_meta_target_down",
      "title": "tortuga_host_meta_target_down",
      "condition": "C",
      "for": "5m",
      "noDataState": "NoData",
      "execErrState": "Error",
      "labels": { "severity": "critical" },
      "annotations": { "summary": "meta target down" },
      "isPaused": false,
      "data": [ ]
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `folder` | Grafana folder **path** (`a/b`), relative to the `alerts/` root (i.e. `alerts/my-perfect-system/...`). Created if missing, like dashboard folders. Use `folderUid` to target a folder directly instead. |
| `title` | Rule group name. |
| `interval` | Group evaluation interval in **seconds**. |
| `rules[]` | Alert rules (Grafana `ProvisionedAlertRule` shape). `folderUID`/`ruleGroup`/`orgID` are filled in at upload time. |
| `data[].datasourceUid` | Use aliases: `${DS_PROMETHEUS}`, `${DS_LOKI}`. Resolved from `data/state/datasources.json` at upload. `__expr__` is left untouched. |

## Ignoring NoData and sensor exceptions

- Rules whose input may legitimately be absent — e.g. the Loki security checks,
  where a quiet log means "nothing happened" — set `"noDataState": "OK"` so a
  missing result does not raise a NoData alert. Use `"NoData"` only for rules
  where absence itself is a problem (e.g. `up == 0` down-detection).
- Sensors that report known false-positive alarms are excluded via the
  recording rule `mps_sensor_excluded`, e.g.
  `(node_hwmon_temp_alarm{job="integrations/unix"} > 0) unless on(chip, sensor) mps_sensor_excluded`.
  Add exceptions in `alerts/my-perfect-system/clusters/tortuga/cluster_recordings.json` (the `cluster_recordings`
  group) — never inline sensor lists in alert queries.

## Recording rules

Recording rules (Grafana-managed, `record` block instead of `condition`) are
consolidated in the cluster's dedicated `cluster_recordings` group, so they are deployed
with `just upload-alerts` like any alert rule. Recorded series are written into
the Prometheus datasource (`record.target_datasource_uid`), so they are ordinary
metrics usable in dashboards, Explore, and any PromQL (`unless on(...)`).

- Metric names use the reserved prefix `mps_`.
- Static lists use the `label_replace(vector(1), ...)` idiom; append more
  entries as `or` terms inside the same `expr`.
- `record.target_datasource_uid` is always `${DS_PROMETHEUS}`.

| Metric | Labels | Meaning | Defined in |
|---|---|---|---|
| `mps_sensor_excluded` | `chip`, `sensor` | Known false-positive hardware sensors | `clusters/tortuga/cluster_recordings.json` (group `cluster_recordings`) |
| `mps_tortuga_host_expected` | `mps_alloy_hostname` | Expected cluster hosts for cluster `tortuga` | `clusters/tortuga/cluster_recordings.json` (group `cluster_recordings`) |

To change an exception or the cluster host list: edit the `cluster_recordings` group
file here, run `just upload-alerts`. No server access, no restarts.

## Upload

```bash
just upload-alerts-dry   # dry-run: print groups/rules + folders
just upload-alerts       # upload every alert group
```

Or directly:

```bash
python -m src upload-alerts --all
python -m src upload-alerts --file alerts/my-perfect-system/clusters/tortuga/host_metrics.json
```

Uploads are idempotent: a rule group is upserted via
`PUT /api/v1/provisioning/folder/{folderUid}/rule-groups/{group}`, so the
local file is the source of truth for that group. The upload sends
`X-Disable-Provenance: true`, so the rules stay editable in the Grafana UI
(they are not marked as provisioned). Run `just discover` first so
datasource aliases resolve.
