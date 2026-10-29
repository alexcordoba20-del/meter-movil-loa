# Instala Python 3.13 para todos los usuarios y lo añade al PATH.
# 1) winget; 2) si no hay winget o falla, instalador oficial de python.org (comprobando la firma).
$ErrorActionPreference = 'Stop'
$args_py = '/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0'

function Hay-Python {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    try { & python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>$null; return $LASTEXITCODE -eq 0 } catch { return $false }
}

if (Hay-Python) { Write-Host '    Python ya estaba instalado.'; exit 0 }

if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host '    Instalando Python con winget...'
    & winget install --id Python.Python.3.13 -e --silent --accept-package-agreements --accept-source-agreements --override $args_py
    if (Hay-Python) { Write-Host '    Python instalado.'; exit 0 }
    Write-Host '    winget no lo consiguio; pruebo con el instalador de python.org.'
}

Write-Host '    Descargando Python de python.org...'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$versiones = @()
try {
    $html = (Invoke-WebRequest 'https://www.python.org/ftp/python/' -UseBasicParsing).Content
    $versiones = [regex]::Matches($html, 'href="(3\.13\.\d+)/"') | ForEach-Object { $_.Groups[1].Value } |
        Sort-Object { [int]($_ -split '\.')[2] } -Descending
} catch {}
$versiones += '3.13.17'
$exe = Join-Path $env:TEMP 'python-instalador.exe'
$bajado = $false
foreach ($v in ($versiones | Select-Object -Unique)) {
    try {
        Invoke-WebRequest "https://www.python.org/ftp/python/$v/python-$v-amd64.exe" -OutFile $exe -UseBasicParsing
        $bajado = $true; Write-Host "    Descargado Python $v."; break
    } catch {}
}
if (-not $bajado) { throw 'No se pudo descargar Python.' }

$firma = Get-AuthenticodeSignature $exe
if ($firma.Status -ne 'Valid' -or $firma.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
    Remove-Item $exe -Force
    throw "El instalador descargado no tiene una firma valida de la Python Software Foundation ($($firma.Status))."
}
Write-Host '    Instalando...'
Start-Process $exe -ArgumentList $args_py -Wait
Remove-Item $exe -Force -ErrorAction SilentlyContinue
if (Hay-Python) { Write-Host '    Python instalado.'; exit 0 }
throw 'Python se instalo pero no aparece en el PATH. Reinicia el PC y vuelve a ejecutar el instalador.'
