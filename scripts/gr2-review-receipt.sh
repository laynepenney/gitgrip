#!/usr/bin/env bash
# gr2-review-receipt.sh — emit a standardized receipt for a gr2-driven review lane.
#
# The tedious, error-prone parts of the R1 receipt are size measurement, wall-time
# arithmetic, and consistent formatting; this does those. The reviewer drives the
# real gr2 commands by hand (create-project / open-project --enter / read+run /
# exit-gr) and captures t0/t1 with `date +%s` around them, then feeds the values here.
#
# Required:
#   --gr-sha <sha>          the gr:<sha> create-project printed (bare sha or gr:-prefixed)
#   --review-root <path>    the review_root open-project --enter reported
#   --t0 <epoch>            wall-clock seconds at `lane create` start
#   --t1 <epoch>            wall-clock seconds at `exit-gr` return
# Optional:
#   --v2-head <sha>         the head the R1 verdict binds to (printed in the receipt)
#   --target <ref@sha>      the review target (e.g. recall dev @ c28f446a)
#   --full-ref <path>       a full (non-sparse) checkout of the same repo to size for a
#                           sparse-savings comparison; omit if none is available
#   --exit-points <file>    a file, one line per point the review forced you OUT of gr2
#                           into raw git/gh/shell; each line is quoted verbatim
#   --lane <name>           review lane name (label only)
#
# Emits a markdown receipt block on stdout. Measures only what is actually present;
# a savings line appears only when --full-ref is given (no fabricated comparison).
set -u
set -o pipefail

GR_SHA="" REVIEW_ROOT="" T0="" T1="" V2_HEAD="" TARGET="" FULL_REF="" EXIT_POINTS="" LANE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --gr-sha) GR_SHA=$2; shift 2;;
    --review-root) REVIEW_ROOT=$2; shift 2;;
    --t0) T0=$2; shift 2;;
    --t1) T1=$2; shift 2;;
    --v2-head) V2_HEAD=$2; shift 2;;
    --target) TARGET=$2; shift 2;;
    --full-ref) FULL_REF=$2; shift 2;;
    --exit-points) EXIT_POINTS=$2; shift 2;;
    --lane) LANE=$2; shift 2;;
    *) echo "gr2-review-receipt: unknown arg: $1" >&2; exit 2;;
  esac
done
GR_SHA=${GR_SHA#gr:}
for req in GR_SHA REVIEW_ROOT T0 T1; do
  if [ -z "${!req}" ]; then echo "gr2-review-receipt: --${req,,} is required" >&2; exit 2; fi
done
[ -d "$REVIEW_ROOT" ] || { echo "gr2-review-receipt: review-root is not a directory: $REVIEW_ROOT" >&2; exit 2; }
case "$T0$T1" in *[!0-9]*) echo "gr2-review-receipt: --t0/--t1 must be epoch seconds" >&2; exit 2;; esac

# --- wall time create -> exit ---
elapsed=$(( T1 - T0 ))
if [ "$elapsed" -lt 0 ]; then echo "gr2-review-receipt: t1 < t0 ($T1 < $T0)" >&2; exit 2; fi
mm=$(( elapsed / 60 )); ss=$(( elapsed % 60 ))

# --- lane sizes: total review_root, plus per materialized repo under repos/ ---
total_kb=$(du -sk "$REVIEW_ROOT" 2>/dev/null | cut -f1)
human() { awk -v k="$1" 'BEGIN{ if(k>=1048576) printf "%.1fG", k/1048576; else if(k>=1024) printf "%.1fM", k/1024; else printf "%dK", k }'; }

per_repo=""
repos_dir="$REVIEW_ROOT/repos"
if [ -d "$repos_dir" ]; then
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    rk=$(du -sk "$d" 2>/dev/null | cut -f1)
    per_repo="${per_repo}  - $(basename "$d"): $(human "$rk")\n"
  done < <(find "$repos_dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
fi

savings=""
if [ -n "$FULL_REF" ] && [ -d "$FULL_REF" ]; then
  full_kb=$(du -sk "$FULL_REF" 2>/dev/null | cut -f1)
  if [ "${full_kb:-0}" -gt 0 ]; then
    # This compares SIZE only. It does NOT certify HOW the tree was produced:
    # a blobless+sparse review-ephemeral clone and a full normal clone are both
    # measured the same way, so the label never claims "sparse" (the pre-push
    # path clones full, and my own recall#856 lane was a full 595M clone).
    if [ "$total_kb" -ge "$full_kb" ]; then
      # At or above the reference is not a saving; a naive percent would go
      # negative and render as "smaller". Say NOT smaller plainly.
      savings="review tree $(human "$total_kb") vs reference $(human "$full_kb") = NOT smaller"
    else
      pct=$(awk -v a="$total_kb" -v b="$full_kb" 'BEGIN{ printf "%.1f", 100*(1-a/b) }')
      savings="review tree $(human "$total_kb") vs reference $(human "$full_kb") = ${pct}% smaller"
    fi
  fi
fi

exit_block=""
if [ -n "$EXIT_POINTS" ] && [ -f "$EXIT_POINTS" ]; then
  # grep -c prints 0 and EXITS 1 on no match; `|| true` swallows the exit without
  # appending a second "0" (which `|| echo 0` did, corrupting the integer test).
  n=$(grep -c . "$EXIT_POINTS" 2>/dev/null || true)
  n=${n:-0}
  if [ "$n" -eq 0 ]; then
    exit_block="CLI exit points: NONE — the whole review ran inside gr2."
  else
    exit_block="CLI exit points ($n — each a place gr2 forced me to raw git/gh/shell):\n$(sed 's/^/  - /' "$EXIT_POINTS")"
  fi
else
  exit_block="CLI exit points: (not recorded — pass --exit-points <file>)"
fi

# --- emit ---
printf '### gr2 review receipt%s\n\n' "${LANE:+ — $LANE}"
printf 'gr commit: gr:%s\n' "$GR_SHA"
[ -n "$TARGET" ]  && printf 'target: %s\n' "$TARGET"
[ -n "$V2_HEAD" ] && printf 'R1 bound to head: %s\n' "$V2_HEAD"
printf 'create -> exit wall time: %dm%02ds (%ds)\n' "$mm" "$ss" "$elapsed"
printf 'review lane total size: %s (%s)\n' "$(human "$total_kb")" "$REVIEW_ROOT"
if [ -n "$per_repo" ]; then printf 'per repo:\n'; printf '%b' "$per_repo"; fi
[ -n "$savings" ] && printf '%s\n' "$savings"
printf '%b\n' "$exit_block"
