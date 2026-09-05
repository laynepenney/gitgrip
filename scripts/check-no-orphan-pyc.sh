#!/usr/bin/env bash
# check-no-orphan-pyc.sh [scan-root]
#
# Refuses a .pyc that has no source, in two ways:
#   (1) a .pyc TRACKED in git — a committed bytecode file is source-less in every
#       fresh checkout and is imported as a GHOST module (pytest collects it, its
#       tests "exist" with no readable source). This is the durable recurrence path
#       and is always meaningful, even on a clean CI checkout.
#   (2) a WORKING-TREE .pyc under scan-root (default: repo root, minus .venv / target /
#       node_modules / .git) whose sibling source .py is absent. Meaningful when run
#       AFTER a test run has populated __pycache__: a source removed while its .pyc
#       lingers shows here.
#
# Why: the release feasibility read found two review tests existing ONLY as stale .pyc
# with no source; the sources have since landed, so this guard keeps the class from
# returning rather than fixing an instance. Wire it into CI AFTER pytest so (2) has a
# populated __pycache__ to scan.
#
# Exit: 0 clean; 1 an orphan or a tracked .pyc was found; 2 usage / not a git tree.
set -u
set -o pipefail

ROOT=${1:-}
if [ -z "$ROOT" ]; then
  ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "check-no-orphan-pyc: not a git work tree and no scan-root given" >&2; exit 2; }
fi
[ -d "$ROOT" ] || { echo "check-no-orphan-pyc: scan-root is not a directory: $ROOT" >&2; exit 2; }

status=0

# (1) tracked .pyc anywhere in the repo
tracked=$(git -C "$ROOT" ls-files '*.pyc' 2>/dev/null || true)
if [ -n "$tracked" ]; then
  echo "TRACKED .pyc (a committed bytecode file is source-less in every checkout):" >&2
  printf '%s\n' "$tracked" | sed 's/^/  /' >&2
  status=1
fi

# (2) working-tree orphans: a .pyc in __pycache__ whose sibling source is gone
while IFS= read -r pyc; do
  [ -n "$pyc" ] || continue
  base=$(basename "$pyc" .pyc)
  stem=${base%%.cpython-*}          # strip .cpython-XY[-pytest-...]; leaves the module name
  srcdir=$(dirname "$(dirname "$pyc")")   # parent of the __pycache__ dir
  if [ ! -f "$srcdir/$stem.py" ]; then
    echo "ORPHAN .pyc (no $srcdir/$stem.py): $pyc" >&2
    status=1
  fi
done < <(find "$ROOT" \
  \( -path '*/.venv' -o -path '*/target' -o -path '*/node_modules' -o -path '*/.git' \) -prune -o \
  -type f -name '*.pyc' -path '*/__pycache__/*' -print 2>/dev/null)

if [ "$status" -eq 0 ]; then
  echo "check-no-orphan-pyc: OK — no tracked .pyc and no source-less .pyc under $ROOT"
fi
exit "$status"
