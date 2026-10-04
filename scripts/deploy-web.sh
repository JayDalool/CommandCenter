#!/usr/bin/env bash
# deploy-web.sh — install the Command Center UI as an atomic release.
#
#   ~/.local/share/command-center/web/
#     releases/<UTC stamp>-<rev>/     one complete build each (index.html + assets/)
#     current -> releases/<…>/        what ccd serves; switched with one rename()
#
# Why: building in place (vite empties dist/) deleted the hashed chunks an
# already-open window still needed, so "open file" failed with "Failed to fetch
# dynamically imported module". Now:
#   1. the new build is written to its own directory, never over the live one;
#   2. it also carries the hashed assets of the last KEEP_ASSETS releases, so a
#      window opened on an older build can still lazy-load its editor/terminal
#      chunks (names are content hashes: they never collide or change meaning);
#   3. every file the new index.html references is checked to exist;
#   4. `current` is switched with an atomic rename — no moment where index.html
#      and its assets disagree; ccd needs no restart (it resolves the link per request);
#   5. only releases older than the newest KEEP_RELEASES are deleted, and never
#      the one `current` points at.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${CCD_WEB_DIR:-$HOME/.local/share/command-center/web}"
KEEP_ASSETS="${KEEP_ASSETS:-3}"
KEEP_RELEASES="${KEEP_RELEASES:-6}"
REV="$(git -C "$REPO" rev-parse --short HEAD)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="$STAMP-$REV"
REL="$BASE/releases/$NAME"
TMP="$BASE/releases/.building-$NAME"

mkdir -p "$BASE/releases"
rm -rf "$TMP"

echo "== build $NAME"
cd "$REPO/web/app"
npm ci --no-audit --no-fund >/dev/null
npx tsc -b
npx vite build --outDir "$TMP" --emptyOutDir --logLevel warn
( cd "$TMP/assets" && ls -1 ) > "$TMP/own-assets.txt"

echo "== carry hashed assets of the last $KEEP_ASSETS releases"
carried=0
for prev in $(ls -1d "$BASE"/releases/[0-9]*/ 2>/dev/null | sort -r | head -n "$KEEP_ASSETS"); do
  [ -f "$prev/own-assets.txt" ] || continue
  while IFS= read -r f; do
    [ -n "$f" ] && [ -f "$prev/assets/$f" ] && [ ! -e "$TMP/assets/$f" ] || continue
    cp -p "$prev/assets/$f" "$TMP/assets/$f"
    carried=$((carried + 1))
  done < "$prev/own-assets.txt"
done
# Extra asset directories to carry (colon-separated), e.g. the repo's web/app/dist that served
# the UI before the first release existed, so windows opened on it keep working too.
IFS=: read -r -a extra <<< "${CARRY_FROM:-}"
if [ ! -e "$BASE/current" ] && [ -d "$REPO/web/app/dist/assets" ]; then extra+=("$REPO/web/app/dist/assets"); fi
for dir in "${extra[@]}"; do
  [ -n "$dir" ] && [ -d "$dir" ] || continue
  for src in "$dir"/*; do
    f="$(basename "$src")"
    [[ "$f" =~ -[A-Za-z0-9_-]{8}\.(js|css|woff2?|ttf|svg|png|wasm)$ ]] || continue   # hashed files only
    [ -e "$TMP/assets/$f" ] && continue
    cp -p "$src" "$TMP/assets/$f"
    echo "$f" >> "$TMP/own-assets.txt"   # seeded files then live as long as this release's own
    carried=$((carried + 1))
  done
done
echo "   carried $carried files"

echo "== verify"
python3 - "$TMP" <<'PY'
import os, re, sys
root = sys.argv[1]
html = open(os.path.join(root, "index.html")).read()
refs = set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', html))
missing = [r for r in refs if not os.path.isfile(os.path.join(root, r.lstrip("/")))]
# every chunk any JS file imports by name must be here too
for name in os.listdir(os.path.join(root, "assets")):
    if name.endswith(".js"):
        text = open(os.path.join(root, "assets", name), encoding="utf-8", errors="replace").read()
        for dep in set(re.findall(r'["\'/]([A-Za-z0-9._-]+-[A-Za-z0-9_-]{8}\.(?:js|css))["\']', text)):
            if not os.path.isfile(os.path.join(root, "assets", dep)):
                missing.append("/assets/" + dep)
if missing or not refs:
    sys.exit("refusing to switch: missing " + ", ".join(sorted(set(missing))[:10]))
print(f"   index references {len(refs)} files, all present")
PY

mv -T "$TMP" "$REL"
ln -sfn "releases/$NAME" "$BASE/current.next"
mv -T "$BASE/current.next" "$BASE/current"     # the atomic switch
echo "== current -> releases/$NAME"

echo "== prune"
cur="$(readlink "$BASE/current")"
ls -1d "$BASE"/releases/[0-9]*/ | sort -r | tail -n +"$((KEEP_RELEASES + 1))" | while read -r old; do
  [ "releases/$(basename "$old")" = "$cur" ] && continue
  rm -rf "$old" && echo "   removed $(basename "$old")"
done
