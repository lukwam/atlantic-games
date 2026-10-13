#!/usr/bin/env bash
# Check that a source distribution is complete: extract it away from the
# checkout, build a wheel from it, install that wheel with the test extras,
# and run the sdist's own offline tests (live tests are deselected).
#
# Usage: scripts/check_sdist.sh dist/PACKAGE-VERSION.tar.gz
set -euo pipefail

sdist=$(realpath "$1")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

tar xzf "$sdist" -C "$work" --strip-components 1
cd "$work"
python -m venv .venv
.venv/bin/python -m pip install -q build
.venv/bin/python -m build -q --wheel --outdir wheel .
wheel=$(ls wheel/*.whl)
.venv/bin/python -m pip install -q "$wheel[api,cli,mcp,test]"
.venv/bin/python -m pytest -q -p no:cacheprovider
