$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$failed = $false
function Check($name, $ok, $details) { if ($ok) { Write-Host "[OK] $($name): $details" -ForegroundColor Green } else { Write-Host "[MISSING] $($name): $details" -ForegroundColor Red; $script:failed = $true } }
$localVenv = Join-Path $root '.venv-local\Scripts\python.exe'
$legacyVenv = Join-Path $root '.venv\Scripts\python.exe'
$venv = if (Test-Path $localVenv) { $localVenv } else { $legacyVenv }
Check 'Python 3.12' (Test-Path $venv) $(if (Test-Path $venv) { (& $venv --version).Trim() } else { 'Create .venv-local with: py -3.12 -m venv .venv-local' })
Check 'Virtual environment' (Test-Path $venv) $(if (Test-Path $venv) { "Using $([IO.Path]::GetFileName((Split-Path -Parent (Split-Path -Parent $venv))).ToString())." } else { 'Missing .venv-local.' })
$node = 'C:\Program Files\nodejs\node.exe'
$npm = 'C:\Program Files\nodejs\npm.cmd'
Check 'Node.js' (Test-Path $node) $(if (Test-Path $node) { (& $node --version).Trim() } else { 'Install Node.js LTS.' })
Check 'npm' (Test-Path $npm) $(if (Test-Path $npm) { (& $npm --version).Trim() } else { 'Install Node.js LTS.' })
if (Test-Path $venv) {
    # `futu` is loaded lazily by the snapshot endpoint, so omitting it here
    # previously let the app start successfully and fail only after a user
    # pressed "拉取".  Verify the exact runtime used by the launcher instead.
    & $venv -c "import fastapi,uvicorn,pandas,numpy,scipy,pydantic,pydantic_settings,multipart,httpx,pytest,webview,PyInstaller,openbb,futu" 2>$null
    Check 'Python packages' ($LASTEXITCODE -eq 0) $(if ($LASTEXITCODE -eq 0) { 'Installed, including Futu OpenD SDK and OpenBB news runtime.' } else { 'Run .venv-local\\Scripts\\python.exe -m pip install -e .[dev] in backend.' })
}
Check 'Frontend packages' (Test-Path (Join-Path $root 'frontend\node_modules')) $(if (Test-Path (Join-Path $root 'frontend\node_modules')) { 'Installed.' } else { 'Run npm install in frontend.' })
if ($failed) { Write-Host 'Environment check failed.' -ForegroundColor Yellow; exit 1 }
Write-Host "Selected Python: $venv" -ForegroundColor Cyan
Write-Host 'Environment check passed.' -ForegroundColor Green
