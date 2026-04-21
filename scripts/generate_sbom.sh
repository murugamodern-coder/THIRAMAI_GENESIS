#!/bin/bash
pip install cyclonedx-bom
cyclonedx-py requirements requirements-base.txt \
  -o sbom-base.json --of JSON
cyclonedx-py requirements requirements-production.txt \
  -o sbom-production.json --of JSON
echo "SBOM generated: sbom-base.json, sbom-production.json"
