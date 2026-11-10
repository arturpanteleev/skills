#!/usr/bin/env bash
# Печатает только переходы состояния PR — для Monitor/фонового запуска у оркестратора.
# Использование: pr-watch.sh [-i секунды] PR [PR ...]
# Строка события: "PR <n>: <state> <mergeStateStatus> <sha8> fail=<N> pending=<N>".
# Пустые «ещё идёт» не печатаются; выход, когда все PR в MERGED или CLOSED.
# Совместим с bash 3.2 (macOS): без ассоциативных массивов.
set -u
interval=90
if [ "${1:-}" = "-i" ]; then interval="$2"; shift 2; fi
[ $# -gt 0 ] || { echo "usage: $0 [-i sec] PR..." >&2; exit 2; }
state_dir=$(mktemp -d "${TMPDIR:-/tmp}/pr-watch.XXXXXX")
trap 'rm -rf "$state_dir"' EXIT
while :; do
  open=0
  for p in "$@"; do
    s=$(gh pr view "$p" --json state,mergeStateStatus,headRefOid \
        -q '.state+" "+.mergeStateStatus+" "+.headRefOid[0:8]' 2>/dev/null) || continue
    c=$(gh pr checks "$p" --json bucket \
        -q '"fail=\([.[]|select(.bucket=="fail")]|length) pending=\([.[]|select(.bucket=="pending")]|length)"' 2>/dev/null)
    case "$s" in MERGED*|CLOSED*) ;; *) open=1 ;; esac
    line="$s ${c:-}"
    # pending меняется на каждом шаге CI — в ключ перехода он не входит
    key="${line% pending=*}"
    prev=$(cat "$state_dir/$p" 2>/dev/null || true)
    if [ "$prev" != "$key" ]; then
      printf '%s' "$key" > "$state_dir/$p"
      case "$s" in
        *CLEAN*|*BEHIND*|*DIRTY*|*UNSTABLE*|MERGED*|CLOSED*) echo "PR $p: $line" ;;
        *) case "${c:-}" in fail=0*|"") ;; *) echo "PR $p: $line" ;; esac ;;
      esac
    fi
  done
  [ "$open" = 1 ] || exit 0
  sleep "$interval"
done
