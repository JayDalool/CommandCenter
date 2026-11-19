#!/usr/bin/env bash
# Read-only check that this machine's time zone data knows Manitoba's permanent UTC−05 (IANA tzdata 2026e+).
# Checks the C library (date, cron, ccd), Python zoneinfo and Node's bundled ICU (vitest, Vite). Changes nothing.
#   scripts/check-tz.sh            on jay-server, a CI runner, or any Linux box (CC-054: also the hosted CI runner)
# Exit 0 when every runtime found reads Winnipeg as −05 on 15 Jan 2027, 1 otherwise.
set -u
AT=2027-01-15T18:00:00Z   # first winter on permanent UTC−05; stale data says −06
fail=0
check() {  # name, offset found
  if [ "$2" = "-0500" ]; then echo "PASS  $1: $2"; else echo "FAIL  $1: ${2:-not readable} (expected -0500)"; fail=1; fi
}

echo "host zone: $(readlink -f /etc/localtime 2>/dev/null || echo unknown)  TZ=${TZ:-unset}"
# CC-054: glibc (date, cron, ccd) reads the zone files from TZDIR when it is set, else /usr/share/zoneinfo, so the
# version printed must come from that same directory; the dpkg package version describes only the default one.
ZDIR=${TZDIR:-/usr/share/zoneinfo}
if [ -n "${TZDIR:-}" ]; then pkg="TZDIR=$TZDIR overrides the system package"
else pkg="package $(dpkg-query -W -f '${Version}' tzdata 2>/dev/null || echo unknown)"; fi
echo "tzdata (C library): $pkg, $(head -1 "$ZDIR/tzdata.zi" 2>/dev/null || echo "tzdata.zi not readable in $ZDIR")"
check "C library (date)" "$(TZ=America/Winnipeg date -d "$AT" +%z 2>/dev/null)"
# CC-054: report the tz data ZoneInfo really reads for America/Winnipeg, in ZoneInfo's own order: the first TZPATH
# directory that holds the zone, and only when none does, the pip tzdata package. The first tzdata.zi on TZPATH can
# sit in a different directory than the zone file, so it is looked up in the directory that supplied the zone.
# zoneinfo reads PYTHONTZPATH from os.environ itself (so -I does not hide it) and ignores relative entries with a
# warning; that native handling is used as is. -B: never write bytecode, because a writable pip tzdata fallback would
# otherwise get __pycache__ files. CHECK_TZ_PYPATH (extra sys.path entry) lets the test stand in for a pip tzdata.
PYSRC='
import sys, os, pathlib, zoneinfo
from datetime import datetime, timezone
if sys.argv[1]: sys.path.append(sys.argv[1])
KEY = "America/Winnipeg"
src = None
for d in zoneinfo.TZPATH:
    if (pathlib.Path(d) / KEY).is_file():
        z = pathlib.Path(d) / "tzdata.zi"
        ver = z.read_text().splitlines()[0] if z.is_file() else "no tzdata.zi in that directory"
        src = f"{d}: {ver}"
        break
else:
    try:
        import tzdata
        src = f"pip tzdata package: {tzdata.IANA_VERSION}"
    except ImportError:
        src = "no source has " + KEY
print("SOURCE", src)
try:
    print("OFFSET", datetime(2027, 1, 15, 18, tzinfo=timezone.utc).astimezone(zoneinfo.ZoneInfo(KEY)).strftime("%z"))
except Exception:
    print("OFFSET")
'
for py in python3 "$(dirname "$0")/../server/.venv/bin/python"; do
  command -v "$py" >/dev/null 2>&1 || continue
  out=$(PYTHONDONTWRITEBYTECODE=1 "$py" -B -I -c "$PYSRC" "${CHECK_TZ_PYPATH:-}" 2>/dev/null)
  echo "tzdata (Python $py): $(printf '%s\n' "$out" | sed -n 's/^SOURCE //p;T;q' | grep . || echo unavailable)"
  check "Python zoneinfo ($py)" "$(printf '%s\n' "$out" | sed -n 's/^OFFSET //p')"
done
if command -v node >/dev/null 2>&1; then
  off=$(node -e '
    const p = new Intl.DateTimeFormat("en-US", {timeZone: "America/Winnipeg", timeZoneName: "longOffset"})
      .formatToParts(new Date(process.argv[1])).find((x) => x.type === "timeZoneName").value;
    console.log(p.replace("GMT", "").replace(":", ""))' "$AT" 2>/dev/null)
  check "Node $(node -v) ICU tz $(node -p process.versions.tz 2>/dev/null)" "$off"
fi
exit $fail
