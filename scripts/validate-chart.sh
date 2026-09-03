#!/usr/bin/env bash
# Chart validation. With helm installed: lint + template every install
# profile. Without helm (restricted CI/sandboxes): structural checks —
# YAML-parse the values files and verify template if/end balance.
set -euo pipefail
CHART="$(cd "$(dirname "$0")/.." && pwd)/helm/modelect"

if command -v helm >/dev/null 2>&1; then
  helm lint "$CHART" --set image.namespace=ci
  helm template t "$CHART" --set image.namespace=ci >/dev/null
  helm template t "$CHART" -f "$CHART/values-management.yaml" \
    --set image.namespace=ci --set database.url=postgresql://x >/dev/null
  helm template t "$CHART" -f "$CHART/values-workload.yaml" \
    --set image.namespace=ci --set agent.controlPlaneUrl=https://x \
    --set agent.token=ma-x --set agent.clusterId=ci >/dev/null
  # profile guards must fail loudly when their requirements are missing
  if helm template t "$CHART" -f "$CHART/values-management.yaml" \
      --set image.namespace=ci >/dev/null 2>&1; then
    echo "FAIL: management profile must require database.url"; exit 1
  fi
  echo "helm lint + template: all profiles PASS"
else
  echo "helm not found — running structural checks only"
  python3 - "$CHART" <<'EOF'
import re, sys, yaml, pathlib
chart = pathlib.Path(sys.argv[1])
for f in ["values.yaml", "values-management.yaml", "values-workload.yaml",
          "Chart.yaml"]:
    yaml.safe_load((chart / f).read_text())
    print(f"  yaml ok: {f}")
for t in sorted((chart / "templates").glob("*.yaml")):
    s = t.read_text()
    opens = len(re.findall(r"{{-?\s*(?:if|range|with|define)\b", s))
    ends = len(re.findall(r"{{-?\s*end\s*-?}}", s))
    assert opens == ends, f"{t.name}: {opens} opens vs {ends} ends"
    print(f"  balanced: {t.name} ({opens} blocks)")
print("structural checks PASS (run with helm for full validation)")
EOF
fi
