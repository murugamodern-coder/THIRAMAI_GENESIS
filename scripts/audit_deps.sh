#!/bin/bash
echo "=== Checking for vulnerabilities ==="
pip install pip-audit --quiet
pip-audit -r requirements-base.txt
pip-audit -r requirements-production.txt
echo "=== Checking for outdated packages ==="
pip list --outdated
echo "=== Done ==="
