# SKV installer for local agents on Windows (Claude Code, Cursor, Claude Desktop).
#   irm https://skv.network/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://skv.network/install.ps1))) -Uninstall
# Options: -Clients "claude-code,cursor,claude-desktop,grok-build"  -NoHooks  -Uninstall  -NoStopGuard  (-StopGuard is accepted; the guard is on by default)
# Nothing is installed without your yes. Key is read hidden, stored in %USERPROFILE%\.skv\key (only your user can read it).
param([switch]$Uninstall, [string]$Clients = "", [switch]$NoHooks, [switch]$StopGuard, [switch]$NoStopGuard)
$ErrorActionPreference = "Stop"
$Base = if ($env:SKV_BASE) { $env:SKV_BASE } else { "https://skv.network" }
$SkvHome = if ($env:SKV_HOME) { $env:SKV_HOME } else { Join-Path $HOME ".skv" }
$Action = if ($Uninstall) { "uninstall" } else { "install" }

$Py = $null
foreach ($c in @("python", "py", "python3")) { if (Get-Command $c -ErrorAction SilentlyContinue) { $Py = (Get-Command $c).Source; break } }
if (-not $Py) { Write-Host "SKV installer needs Python 3 (https://www.python.org/downloads/). Nothing changed."; return }

function Ask($q) { $a = Read-Host "$q [y/N]"; return ($a -match '^(y|Y|д|Д)') }
function Fetch($name, $dest) {
  if ($env:SKV_SRC_DIR) { Copy-Item (Join-Path $env:SKV_SRC_DIR $name) $dest -Force }
  else { Invoke-WebRequest -UseBasicParsing "$Base/install/$name" -OutFile $dest }
}
function Lock($path) {  # owner-only ACL
  icacls $path /inheritance:r /grant:r "$($env:USERNAME):(F)" | Out-Null
}

New-Item -ItemType Directory -Force $SkvHome | Out-Null
Lock $SkvHome
Fetch "skv_config.py" (Join-Path $SkvHome "skv_config.py")

$det = @{
  "claude-code"    = (Get-Command claude -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.claude") -or (Test-Path "$HOME\.claude.json")
  "cursor"         = (Test-Path "$HOME\.cursor")
  "claude-desktop" = (Test-Path "$env:APPDATA\Claude")
  "grok-build"     = (Get-Command grok -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.grok")
}
$label = @{ "claude-code" = "Claude Code (MCP + hooks)"; "cursor" = "Cursor (MCP + hooks)"; "claude-desktop" = "Claude Desktop (MCP only, needs Node.js; no hooks there)"; "grok-build" = "Grok Build (hooks only; its MCP connection is set in Grok Build)" }
$sel = @()
if ($Clients) { $sel = $Clients.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
else {
  foreach ($c in @("claude-code", "cursor", "claude-desktop", "grok-build")) {
    if ($det[$c]) {
      $verb = if ($Action -eq "install") { "Connect SKV to" } else { "Remove SKV from" }
      if (Ask "$verb $($label[$c])?") { $sel += $c }
    }
  }
}
if ($sel.Count -eq 0) { Write-Host "Nothing selected. Nothing changed."; return }

$KeyFile = Join-Path $SkvHome "key"
if ($Action -eq "install") {
  if (-not (Test-Path $KeyFile) -or (Ask "A key is already saved in $KeyFile. Replace it?")) {
    $sec = Read-Host "Paste your SKV key (sk_... from $Base/profile; hidden)" -AsSecureString
    $k = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)).Trim()
    if (-not $k.StartsWith("sk_")) { Write-Host "That does not look like an SKV key (sk_...). Nothing changed."; return }
    [IO.File]::WriteAllText($KeyFile, $k); Lock $KeyFile; Remove-Variable k
  }
  if (-not $NoHooks) { Fetch "skv_hook.py" (Join-Path $SkvHome "skv_hook.py") }
  if (-not $NoStopGuard -and -not $NoHooks) { New-Item -ItemType File -Force (Join-Path $SkvHome "guard") | Out-Null; Write-Host "Stop guard ON by default. Turn it off: delete $SkvHome\guard (or re-run with -NoStopGuard). Pause everything: create $SkvHome\off" }
  else { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $SkvHome "guard"); Write-Host "Stop guard OFF" }
}
$env:SKV_NO_HOOKS = if ($NoHooks) { "1" } else { "0" }
foreach ($c in $sel) {
  Write-Host "== $c"
  & $Py (Join-Path $SkvHome "skv_config.py") $Action $c $SkvHome $Base
  if ($c -ne "claude-desktop" -and $Action -eq "install") {
    foreach ($f in @("$HOME\.claude.json", "$HOME\.cursor\mcp.json")) { if (Test-Path $f) { Lock $f } }
  }
}
if ($Action -eq "install") {
  if (-not $NoHooks) { Write-Host "== test turn"; & $Py (Join-Path $SkvHome "skv_hook.py") test }
  Write-Host "Done. Restart the selected apps. Pause saving: create the file $SkvHome\off. Remove: & ([scriptblock]::Create((irm $Base/install.ps1))) -Uninstall"
} else {
  if (Ask "Also delete $SkvHome (your saved key and hook)?") { Remove-Item -Recurse -Force $SkvHome; Write-Host "Deleted $SkvHome" }
  Write-Host "Done. Backups of changed files are next to them (*.skv-bak.*)."
}
