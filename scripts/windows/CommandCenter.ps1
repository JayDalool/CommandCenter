# Command Center — Windows launcher (browser phase). Not installed anywhere yet.
#
#   powershell -ExecutionPolicy Bypass -File CommandCenter.ps1 [-HostAlias jay-server] [-Port 7777]
#
# 1. keeps an SSH tunnel 127.0.0.1:$Port -> jay-server:127.0.0.1:7777 up (reconnects)
# 2. copies the ccd token to the clipboard over that same SSH trust (never a URL)
# 3. opens http://127.0.0.1:$Port — paste the token once (tick "remember" to skip next time)
#
# Requires OpenSSH (built into Windows 10/11) and key-based login to the host alias.
param([string]$HostAlias = "jay-server", [int]$Port = 7777)
$ErrorActionPreference = "Stop"

function Test-Tunnel { try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$Port/api/health").StatusCode -eq 200 } catch { $false } }

if (-not (Test-Tunnel)) {
  # A hidden loop so the tunnel comes back after sleep or Wi-Fi changes.
  $loop = "while (`$true) { ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -L ${Port}:127.0.0.1:7777 $HostAlias; Start-Sleep 3 }"
  Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", $loop | Out-Null
  for ($i = 0; $i -lt 20 -and -not (Test-Tunnel); $i++) { Start-Sleep -Milliseconds 500 }
}
if (-not (Test-Tunnel)) { Write-Error "Tunnel did not come up. Try: ssh $HostAlias" }

# The token goes straight from ssh to the clipboard; it is not echoed.
ssh $HostAlias "cat .config/command-center/ccd.token" | Set-Clipboard
Start-Process "http://127.0.0.1:$Port"
Write-Host "Command Center open. Token is on the clipboard (paste it once). Tunnel keeps running in the background."
