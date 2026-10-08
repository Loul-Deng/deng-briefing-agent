# Register a daily 08:00 briefing. The clock is the machine local time
# (this PC is UTC+8, which is Beijing time). The agent does not sleep until 08:00.
# StartWhenAvailable: if the lid was closed at 08:00, run as soon as the PC wakes.
# ASCII-only on purpose: Windows PowerShell 5 mis-parses UTF-8 comments without BOM.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Main = Join-Path $Root "main.py"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "python not found: $Python"
}

$TaskName = "DENG-daily-briefing"
$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Main`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At "08:00"
# Laptops skip tasks on battery unless these two flags are set.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
# Interactive current user, so the task can read the repo .env. Do not use SYSTEM.
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
Write-Output "registered $TaskName at 08:00 -> $Python $Main (cwd $Root)"
