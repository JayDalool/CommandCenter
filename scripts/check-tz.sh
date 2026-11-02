#!/usr/bin/env bash
# Read-only check that this machine's time zone data knows Manitoba's permanent UTC−05 (IANA tzdata 2026e+).
# Checks the C library (date, cron, ccd), Python zoneinfo and Node's bundled ICU (vitest, Vite). Changes nothing.
#   scripts/check-tz.sh            on jay-server, the WSL CI runner, or any Linux box
# Exit 0 when every runtime found reads Winnipeg as −05 on 15 Jan 2027, 1 otherwise.
set -u
AT=2027-01-15T18:00:00Z   # first winter on permanent UTC−05; stale data says −06
fail=0
check() {  # name, offset found
  if [ "$2" = "-0500" ]; then echo "PASS  $1: $2"; else echo "FAIL  $1: ${2:-not readable} (expected -0500)"; fail=1; fi
}

echo "host zone: $(readlink -f /etc/localtime 2>/dev/null || echo unknown)  TZ=${TZ:-unset}"
echo "tzdata: $( (dpkg-query -W -f '${Version}' tzdata 2>/dev/null || head -1 /usr/share/zoneinfo/tzdata.zi 2>/dev/null) )"
check "C library (date)" "$(TZ=America/Winnipeg date -d "$AT" +%z 2>/dev/null)"
for py in python3 "$(dirname "$0")/../server/.venv/bin/python"; do
  command -v "$py" >/dev/null 2>&1 || continue
  check "Python zoneinfo ($py)" "$("$py" -I -c "
from datetime import datetime, timezone; from zoneinfo import ZoneInfo
print(datetime(2027, 1, 15, 18, tzinfo=timezone.utc).astimezone(ZoneInfo('America/Winnipeg')).strftime('%z'))" 2>/dev/null)"
done
if command -v node >/dev/null 2>&1; then
  off=$(node -e '
    const p = new Intl.DateTimeFormat("en-US", {timeZone: "America/Winnipeg", timeZoneName: "longOffset"})
      .formatToParts(new Date(process.argv[1])).find((x) => x.type === "timeZoneName").value;
    console.log(p.replace("GMT", "").replace(":", ""))' "$AT" 2>/dev/null)
  check "Node $(node -v) ICU tz $(node -p process.versions.tz 2>/dev/null)" "$off"
fi
exit $fail
