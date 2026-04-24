#!/usr/bin/env bash
# productteam-v2/scripts/verify-release.sh — Phase 1 release gate.
#
# Read-only verification of productteam-v2's pre-release readiness. Checks:
#   1. Test suite (pytest -m "not live")
#   2. Version lockstep across up to 5 surfaces (extracted where they exist)
#   3. Required Rule 9 doc artifacts present on disk
#
# Exit 0 when every check passes; exit 1 on any failure. Never writes.
# Does NOT call bump_version.py. Does NOT invoke the pypi-release skill.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FAILED=0
pass() { printf '  \033[0;32m[PASS]\033[0m %s\n' "$*"; }
fail() { printf '  \033[0;31m[FAIL]\033[0m %s\n' "$*" >&2; FAILED=1; }
info() { printf '\n\033[1;34m%s\033[0m\n' "$*"; }

# --- 1. pytest ---------------------------------------------------------------
info "1. pytest (excluding live)"
if python -m pytest -m "not live" -v --tb=short; then
    pass "test suite green"
else
    fail "pytest failed"
fi

# --- 2. version lockstep across 5 surfaces -----------------------------------
info "2. version lockstep"

declare -a SURFACES=()
declare -a VALUES=()

# extract <label> <file> <grep-ere> <sed-ere>
extract() {
    local label="$1" file="$2" gregex="$3" sedexpr="$4"
    if [ ! -f "$file" ]; then
        return 0
    fi
    local val
    val=$(grep -oE "$gregex" "$file" 2>/dev/null | head -1 | sed -E "$sedexpr")
    if [ -z "${val:-}" ]; then
        val="<no match>"
    fi
    SURFACES+=("$label")
    VALUES+=("$val")
}

extract "pyproject.toml" "pyproject.toml" \
    '^version[[:space:]]*=[[:space:]]*"[^"]+"' \
    's/^version[[:space:]]*=[[:space:]]*"([^"]+)"/\1/'

extract "src/productteam/__init__.py" "src/productteam/__init__.py" \
    '__version__[[:space:]]*=[[:space:]]*"[^"]+"' \
    's/.*"([^"]+)"/\1/'

extract "CHANGELOG.md" "CHANGELOG.md" \
    '^##[[:space:]]*\[[0-9]+\.[0-9]+\.[0-9]+\]' \
    's/^##[[:space:]]*\[([0-9]+\.[0-9]+\.[0-9]+)\].*/\1/'

extract "docs/index.html" "docs/index.html" \
    'ProductTeam v[0-9]+\.[0-9]+\.[0-9]+' \
    's/ProductTeam v([0-9]+\.[0-9]+\.[0-9]+)/\1/'

extract "docs/architecture.svg" "docs/architecture.svg" \
    'v[0-9]+\.[0-9]+\.[0-9]+' \
    's/v([0-9]+\.[0-9]+\.[0-9]+)/\1/'

if [ "${#SURFACES[@]}" -eq 0 ]; then
    fail "no version surfaces found"
else
    for i in "${!SURFACES[@]}"; do
        printf '      %-34s %s\n' "${SURFACES[$i]}" "${VALUES[$i]}"
    done
    UNIQ=$(printf '%s\n' "${VALUES[@]}" | sort -u | grep -vE '^<no match>$' | wc -l | tr -d ' ')
    if [ "$UNIQ" -eq 1 ]; then
        pass "one unique version across ${#SURFACES[@]} surface(s)"
    else
        fail "version drift: $UNIQ unique values across ${#SURFACES[@]} surface(s)"
    fi
fi

# --- 3. required docs --------------------------------------------------------
info "3. required docs present"
for f in README.md CHANGELOG.md CONTRIBUTING.md LICENSE .gitignore docs/index.html; do
    if [ -f "$f" ]; then
        pass "$f"
    else
        fail "missing: $f"
    fi
done

# --- summary -----------------------------------------------------------------
echo ""
if [ "$FAILED" -eq 0 ]; then
    printf '\033[0;32mVERIFY-RELEASE: PASSED\033[0m\n'
    exit 0
else
    printf '\033[0;31mVERIFY-RELEASE: FAILED\033[0m\n'
    exit 1
fi
