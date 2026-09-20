# alerts/

Local store for Grafana alert rule groups (Grafana Alerting provisioning
format). Each JSON file describes **one rule group**; the folder tree mirrors
Grafana folders, exactly like `dashboards/tested/`.

```
alerts/
  my-perfect-system/
    meta-monitoring/
      alloy-health.json
```

## File format

```json
{
  "folder": "my-perfect-system/meta-monitoring",
  "orgId": 1,
  "title": "alloy-health",
  "interval": 60,
  "rules": [
    {
      "uid": "alloy-target-down",
      "title": "Alloy target down",
      "condition": "C",
      "for": "5m",
      "noDataState": "NoData",
      "execErrState": "Error",
      "labels": { "severity": "critical" },
      "annotations": { "summary": "Alloy is down" },
      "isPaused": false,
      "data": [ ]
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `folder` | Grafana folder **path** (`a/b`). Created if missing, like dashboard folders. Use `folderUid` to target a folder directly instead. |
| `title` | Rule group name. |
| `interval` | Group evaluation interval in **seconds**. |
| `rules[]` | Alert rules (Grafana `ProvisionedAlertRule` shape). `folderUID`/`ruleGroup`/`orgID` are filled in at upload time. |
| `data[].datasourceUid` | Use aliases: `${DS_PROMETHEUS}`, `${DS_LOKI}`. Resolved from `data/state/datasources.json` at upload. `__expr__` is left untouched. |

## Upload

```bash
just upload-alerts-dry   # dry-run: print groups/rules + folders
just upload-alerts       # upload every alert group
```

Or directly:

```bash
python -m src upload-alerts --all
python -m src upload-alerts --file alerts/my-perfect-system/meta-monitoring/alloy-health.json
```

Uploads are idempotent: a rule group is upserted via
`PUT /api/v1/provisioning/folder/{folderUid}/rule-groups/{group}`, so the
local file is the source of truth for that group. The upload sends
`X-Disable-Provenance: true`, so the rules stay editable in the Grafana UI
(they are not marked as provisioned). Run `just discover` first so
datasource aliases resolve.
