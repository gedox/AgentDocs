# Creates "Launch AgentDocs.lnk" in the project root, pointing at AgentDocs.bat
# with the app icon attached.
#
#     powershell -ExecutionPolicy Bypass -File assets\make_launcher.ps1
#
# The shortcut is machine-specific (it stores absolute paths), which is why it
# is generated locally rather than committed.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "AgentDocs.bat"
$icon = Join-Path $root "assets\agentdocs.ico"
$link = Join-Path $root "Launch AgentDocs.lnk"

if (-not (Test-Path -LiteralPath $target)) { throw "Missing $target" }

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($link)
$s.TargetPath = $target
$s.WorkingDirectory = $root
if (Test-Path -LiteralPath $icon) { $s.IconLocation = "$icon,0" }
$s.Description = "Launch the AgentDocs UI (documentation browser + blueprint generator)"
$s.WindowStyle = 7   # start minimised; the UI opens in your browser
$s.Save()

Write-Host "Created: $link"
