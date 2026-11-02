#!/usr/bin/env bash
# Static checks for every tracked file, no install needed (ops #329). Run it the same way CI does:
#   bash .github/ci/static_checks.sh
#
#   1. bash -n on every shell script (a *.sh file, or a file whose first line is a sh/bash shebang)
#   2. shellcheck at error severity: any finding fails. Warnings are printed, never fail.
#   3. every tracked *.json, *.yml and *.yaml parses (needs PyYAML)
#   4. every tracked *.py compiles (python3 -I)
#
# Prints every problem it finds, then exits 1 if there was one. Exit 2 means the check itself
# could not run (no shellcheck, no python), which also fails the PR.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || exit 2
fail=0

# --- shell scripts ---------------------------------------------------------------------------
sh_files=()
while IFS= read -r -d '' f; do
  [ -f "$f" ] || continue
  case "$f" in
    *.sh) sh_files+=("$f") ;;
    *.*) ;;
    *) head -n1 "$f" 2>/dev/null | grep -aqE '^#!.*(ba|da|k)?sh([[:space:]]|$)' && sh_files+=("$f") ;;
  esac
done < <(git ls-files -z)

echo "== bash -n on ${#sh_files[@]} shell script(s)"
for f in "${sh_files[@]}"; do
  if ! out=$(bash -n "$f" 2>&1); then
    echo "::error file=$f::bash -n failed: $out"
    fail=1
  fi
done

if [ "${#sh_files[@]}" -gt 0 ]; then
  command -v shellcheck >/dev/null || { echo "shellcheck is not installed" >&2; exit 2; }
  echo "== shellcheck (errors fail, warnings are listed)"
  # Warnings first, as annotations only.
  shellcheck -S warning -f gcc "${sh_files[@]}" 2>/dev/null | grep -E ': warning: ' \
    | sed -E 's/^([^:]+):([0-9]+):([0-9]+): warning: (.*)$/::warning file=\1,line=\2,col=\3::\4/' | head -n 50
  raw=$(shellcheck -S error -f gcc "${sh_files[@]}" 2>&1)
  rc=$?
  if [ "$rc" -gt 1 ]; then
    echo "$raw"; echo "shellcheck could not process every file (exit $rc)" >&2; exit 2
  elif [ "$rc" -eq 1 ]; then
    printf '%s\n' "$raw" | sed -E 's/^([^:]+):([0-9]+):([0-9]+): error: (.*)$/::error file=\1,line=\2,col=\3::\4/'
    fail=1
  fi
fi

# --- config files and python -----------------------------------------------------------------
command -v python3 >/dev/null || { echo "python3 is not installed" >&2; exit 2; }
echo "== config files parse, python compiles"
git ls-files -z -- '*.json' '*.yml' '*.yaml' '*.py' | python3 -I -W ignore -c '
import ast, json, os, sys
try:
    import yaml
except ImportError:
    print("PyYAML is not installed (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)
names = [n for n in sys.stdin.buffer.read().decode().split("\0") if n and os.path.isfile(n)]
bad = 0
for n in names:
    try:
        with open(n, "rb") as fh:
            data = fh.read()
        if n.endswith(".json"):
            json.loads(data)
        elif n.endswith((".yml", ".yaml")):
            list(yaml.safe_load_all(data))
        else:
            compile(data, n, "exec", dont_inherit=True)
    except Exception as e:
        bad += 1
        print("::error file=%s::%s: %s" % (n, type(e).__name__, str(e).replace("\n", " ")))
print("checked %d file(s), %d problem(s)" % (len(names), bad))
sys.exit(1 if bad else 0)
' || { [ $? -eq 1 ] && fail=1 || exit 2; }

if [ "$fail" -ne 0 ]; then
  echo "static checks FAILED" >&2
  exit 1
fi
echo "static checks passed"
