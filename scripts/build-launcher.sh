#!/usr/bin/env bash
# Build the Windows launcher CommandCenter.exe from launcher/.
#
#   scripts/build-launcher.sh
#
# Runs go vet + go test, cross-compiles a GUI-subsystem exe (no console), checks
# it is a PE/GUI binary with no credential strings in it, and writes
#   CommandCenter.exe, CommandCenter.exe.sha256, launcher.json
# into ${CCD_LAUNCHER_DIR:-$HOME/.local/share/command-center/launcher}/.
# Needs Go (uses ~/.local/go/bin/go when it is not on PATH).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$repo/launcher"
out="${CCD_LAUNCHER_DIR:-$HOME/.local/share/command-center/launcher}"
version="${CCD_LAUNCHER_VERSION:-0.1.0}"

if ! command -v go >/dev/null 2>&1; then
  export PATH="$HOME/.local/go/bin:$PATH"
fi
export GOPATH="${GOPATH:-$HOME/.cache/go}" GOCACHE="${GOCACHE:-$HOME/.cache/go-build}" GOMODCACHE="${GOMODCACHE:-$HOME/.cache/go/mod}"
export GOFLAGS="${GOFLAGS:-} -mod=readonly" GOTOOLCHAIN=local

commit="$(git -C "$repo" rev-parse --short HEAD)"
if [ -n "$(git -C "$repo" status --porcelain -- launcher)" ]; then
  commit="$commit-dirty"
fi
built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cd "$src"
echo "== $(go version)"
echo "== go vet (linux + windows)"
go vet ./...
GOOS=windows GOARCH=amd64 go vet ./...
echo "== go test"
go test -count=1 ./...

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "== build $version ($commit)"
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath \
  -ldflags "-H windowsgui -s -w -X main.version=$version -X main.commit=$commit" \
  -o "$tmp/CommandCenter.exe" .

echo "== check PE/GUI and no credential strings"
python3 - "$tmp/CommandCenter.exe" <<'PY'
import struct, sys
data = open(sys.argv[1], "rb").read()
assert data[:2] == b"MZ", "not an MZ executable"
pe = struct.unpack_from("<I", data, 0x3C)[0]
assert data[pe:pe + 4] == b"PE\0\0", "no PE signature"
machine = struct.unpack_from("<H", data, pe + 4)[0]
opt = pe + 24
magic = struct.unpack_from("<H", data, opt)[0]
subsystem = struct.unpack_from("<H", data, opt + 68)[0]
assert machine == 0x8664, "not amd64 (machine=%#x)" % machine
assert magic == 0x20B, "not PE32+ (magic=%#x)" % magic
assert subsystem == 2, "subsystem %d is not 2 (Windows GUI)" % subsystem
bad = [s for s in (b"ccd.token", b"developer.token", b"BEGIN OPENSSH", b"BEGIN RSA PRIVATE",
                   b"github_pat_", b"X-CCD-Token", b"id_ed25519", b"id_rsa", b"/home/")
       if s in data]
assert not bad, "binary contains %r" % bad
print("PE32+ amd64, subsystem 2 (GUI), no credential strings")
PY

sha="$(sha256sum "$tmp/CommandCenter.exe" | cut -d' ' -f1)"
size="$(stat -c %s "$tmp/CommandCenter.exe")"
echo "$sha  CommandCenter.exe" > "$tmp/CommandCenter.exe.sha256"
python3 - "$tmp/launcher.json" "$version" "$sha" "$commit" "$built_at" "$size" <<'PY'
import json, sys
path, version, sha, commit, built_at, size = sys.argv[1:]
with open(path, "w") as f:
    json.dump({"version": version, "sha256": sha, "commit": commit,
               "built_at": built_at, "size": int(size)}, f, indent=2)
    f.write("\n")
PY

mkdir -p "$out"
for f in CommandCenter.exe CommandCenter.exe.sha256 launcher.json; do
  install -m 0644 "$tmp/$f" "$out/$f.new" && mv -f "$out/$f.new" "$out/$f"
done
echo "== wrote $out"
echo "   CommandCenter.exe  $size bytes"
echo "   sha256  $sha"
