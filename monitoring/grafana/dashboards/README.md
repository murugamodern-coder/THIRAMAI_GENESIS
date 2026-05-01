# Thiramai Grafana dashboards

Ten dashboards backed by the metrics defined in
`services/observability/business_metrics.py` and the existing
`prometheus_fastapi_instrumentator` `/metrics` endpoint mounted in `app.py`.

| File | UID | Purpose |
| --- | --- | --- |
| `overview.json` | `thiramai-overview` | CPU / memory / latency / error rate |
| `decisions.json` | `thiramai-decisions` | Decision routing, latency, confidence (PolicyEngine vs legacy) |
| `trading.json` | `thiramai-trading` | PnL, positions, win rate, drawdown |
| `bandit.json` | `thiramai-bandit` | LinUCB exploration / regret / θ-norm |
| `world_model.json` | `thiramai-world-model` | Bayesian world-model evidence + predictions |
| `online_learner.json` | `thiramai-online-learner` | SGD accuracy / drift / retrains |
| `risk.json` | `thiramai-risk` | VaR, sector concentration, drawdown |
| `broker.json` | `thiramai-broker` | Order latency / errors / throughput |
| `alerts.json` | `thiramai-alerts` | SLO violations, error rates, kill-switches |
| `business.json` | `thiramai-business` | Revenue, decisions/day, inventory |

## Datasource

Every dashboard references the Prometheus datasource UID `PROMETHEUS_DS_UID`.
Replace this token at provisioning time (or update Grafana's default datasource
UID to match).

## Provisioning

Drop the dashboards into Grafana's provisioning path
(`/etc/grafana/provisioning/dashboards/`) and add a provider config:

```yaml
apiVersion: 1
providers:
  - name: thiramai
    orgId: 1
    folder: Thiramai
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /etc/grafana/provisioning/dashboards/thiramai
```
