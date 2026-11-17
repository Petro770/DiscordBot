# Install the project dependencies into a local virtual environment.
$ErrorActionPreference = 'Stop'
$venv = Join-Path $PSScriptRoot '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$requirements = Join-Path $PSScriptRoot 'requirements.txt'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    if (Get-Command py -CommandType Application -ErrorAction SilentlyContinue) {
        $bootstrap = 'py'
    } elseif (Get-Command python -CommandType Application -ErrorAction SilentlyContinue) {
        $bootstrap = 'python'
    } else {
        throw 'Install Python 3.10 or newer and run install.ps1 again.'
    }

    & $bootstrap -c 'import sys; sys.exit(sys.version_info < (3, 10))'
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 3.10 or newer is required.'
    }
    & $bootstrap -m venv $venv
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create .venv.'
    }
}

& $python -m pip install --disable-pip-version-check -r $requirements
if ($LASTEXITCODE -ne 0) {
    throw 'Dependency installation failed. See the pip output above.'
}

& (Join-Path $PSScriptRoot 'launch.ps1') -CheckOnly
