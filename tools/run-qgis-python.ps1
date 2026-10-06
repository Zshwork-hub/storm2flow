param(
    [string]$QgisRoot = 'D:\QGIS 3.44.14',
    [Parameter(Mandatory = $true)][string[]]$PythonArguments
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonExecutable = Join-Path $QgisRoot 'bin\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "QGIS Python not found: $pythonExecutable"
}
$savedEnvironment = @{}
$names = @('PYTHONHOME', 'PYTHONPATH', 'QGIS_PREFIX_PATH', 'GDAL_DATA', 'PROJ_DATA', 'MPLCONFIGDIR', 'PATH')
foreach ($name in $names) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
Push-Location $projectRoot
try {
    $env:PYTHONHOME = Join-Path $QgisRoot 'apps\Python312'
    $env:PYTHONPATH = "$(Join-Path $QgisRoot 'apps\qgis-ltr\python');$(Join-Path $QgisRoot 'apps\qgis-ltr\python\plugins')"
    $env:QGIS_PREFIX_PATH = Join-Path $QgisRoot 'apps\qgis-ltr'
    $env:GDAL_DATA = Join-Path $QgisRoot 'apps\gdal\share\gdal'
    $env:PROJ_DATA = Join-Path $QgisRoot 'share\proj'
    $env:MPLCONFIGDIR = Join-Path $projectRoot 'results\mpl-cache'
    $env:PATH = "$(Join-Path $QgisRoot 'bin');$(Join-Path $QgisRoot 'apps\qgis-ltr\bin');$env:PATH"
    & $pythonExecutable @PythonArguments
    $resultCode = $LASTEXITCODE
} finally {
    Pop-Location
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
}
exit $resultCode
