# Registra (o actualiza) la tarea que arranca vigilar_parche.py al iniciar sesión.
# Necesita administrador (la tarea va con privilegios altos para reiniciar LOA Logs sin UAC).
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$py = (Get-Command python).Source
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
$script = Join-Path $dir 'vigilar_parche.py'
$nombre = 'Meter movil - parche LOA Logs'
$usuario = "$env:USERDOMAIN\$env:USERNAME"

$a = New-ScheduledTaskAction -Execute $pyw -Argument "`"$script`"" -WorkingDirectory $dir
$t = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$p = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Highest
$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
     -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $nombre -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null

# Para el vigilante anterior (si lo hay) y arranca el nuevo
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'vigilar_parche' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName $nombre
Write-Host "    Tarea '$nombre' registrada y en marcha ($pyw)."
