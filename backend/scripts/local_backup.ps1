# Weekly local backup for the founder's laptop (Windows Task Scheduler runs this).
# Reads secrets from the private folder %USERPROFILE%\.saxs-team-hub (render.env, backup.key),
# writes an encrypted backup to %USERPROFILE%\.saxs-team-hub\backups and logs to backup.log there.
# Never prints secrets. Backups are kept (never deleted by this script).
$ErrorActionPreference = "Stop"
$home_dir = Join-Path $env:USERPROFILE ".saxs-team-hub"
$backend = Split-Path -Parent $PSScriptRoot
$python = Join-Path $backend ".venv\Scripts\python.exe"
$log = Join-Path $home_dir "backup.log"
$outDir = Join-Path $home_dir "backups"
New-Item -ItemType Directory -Force $outDir | Out-Null

function Read-EnvValue([string]$file, [string]$key) {
    foreach ($line in Get-Content $file) {
        if ($line -match "^\s*$key=(.*)$") { return $Matches[1].Trim() }
    }
    throw "$key not found in $file"
}

try {
    $env:DATABASE_URL = Read-EnvValue (Join-Path $home_dir "render.env") "BACKUP_DATABASE_URL"
    $env:BACKUP_KEY = (Get-Content (Join-Path $home_dir "backup.key") -Raw).Trim()
    Remove-Item Env:MIGRATION_DATABASE_URL -ErrorAction SilentlyContinue
    $file = Join-Path $outDir ("teamhub-{0}.bak" -f (Get-Date -Format "yyyy-MM-dd-HHmm"))
    Push-Location $backend
    $result = & $python -m scripts.backup backup $file 2>&1 | Out-String
    $code = $LASTEXITCODE
    Pop-Location
    $result = $result -replace "postgres(ql)?://\S+", "<redacted>"
    Add-Content $log ("{0} exit={1} {2}" -f (Get-Date -Format s), $code, $result.Trim())
    exit $code
} catch {
    Add-Content $log ("{0} ERROR {1}" -f (Get-Date -Format s), ($_.Exception.Message -replace "postgres(ql)?://\S+", "<redacted>"))
    exit 1
}
