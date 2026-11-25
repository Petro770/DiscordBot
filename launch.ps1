param(
    [ValidateSet('Gui', 'Main')]
    [string]$Mode = 'Gui',
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$requirements = Join-Path $PSScriptRoot 'requirements.txt'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Run install.ps1 to create the project virtual environment.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    & $python -c 'import sys; sys.exit(sys.version_info < (3, 10))'
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 3.10 or newer is required. Recreate .venv with a supported Python.'
    }

    & $python -m pip install --dry-run --no-index --disable-pip-version-check --quiet -r $requirements
    if ($LASTEXITCODE -ne 0) {
        throw 'Required packages are missing or incompatible. Run install.ps1.'
    }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw 'Dependency conflicts found. Run install.ps1.'
    }

    $module = if ($Mode -eq 'Main') { 'main' } else { 'gui_launcher' }
    $imports = if ($CheckOnly) { 'import main, gui_launcher' } else { "import $module" }
    & $python -c $imports
    if ($LASTEXITCODE -ne 0) {
        throw 'Application import failed. See the Python error above.'
    }
    if ($CheckOnly) {
        Write-Host 'Dependency checks passed for main.py and gui_launcher.py.'
        return
    }

    & $python "$module.py"
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
