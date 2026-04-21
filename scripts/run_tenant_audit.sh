#!/usr/bin/env bash
echo "Running tenant isolation audit..."
mkdir -p reports
pytest tests/test_tenant_isolation.py -v \
  --tb=short \
  --junit-xml=reports/tenant_isolation_report.xml
echo "Report saved to reports/tenant_isolation_report.xml"
