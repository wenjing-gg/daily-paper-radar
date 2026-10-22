param(
    [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$Time = "10:30",
    [string]$TaskName = "daily-paper-radar",
    [string]$Python = "python",
    [string]$Profile = "",
    [string]$StateDir = "",
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$LegacyTaskName = "arxiv-radar"
if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    if ($TaskName -eq "daily-paper-radar" -and (Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue)) {
        Unregister-ScheduledTask -TaskName $LegacyTaskName -Confirm:$false
    }
    exit 0
}
$Root = Split-Path $PSScriptRoot -Parent
if (-not $Profile) { $Profile = Join-Path $Root "config\profile.json" }
if (-not $StateDir) { $StateDir = Join-Path $Root "state" }
$Profile = [IO.Path]::GetFullPath($Profile)
$StateDir = [IO.Path]::GetFullPath($StateDir)
$PythonPath = & $Python -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ is required'; print(sys.executable)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required." }
$PythonPath = "$PythonPath".Trim()
& (Join-Path $PSScriptRoot "run_daily.ps1") -Python $PythonPath -Profile $Profile -StateDir $StateDir -Check
if ($LASTEXITCODE -ne 0) { throw "Configuration check failed." }
$Runner = Join-Path $PSScriptRoot "run_daily.ps1"
foreach ($Value in @($Runner, $PythonPath, $Profile, $StateDir)) {
    if ($Value.Contains('"')) { throw "Paths cannot contain quotes." }
}
$Arguments = '-NoProfile -NonInteractive -File "{0}" -Python "{1}" -Profile "{2}" -StateDir "{3}"' -f $Runner, $PythonPath, $Profile, $StateDir
$Action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $Arguments -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.Add([TimeSpan]::Parse($Time)))
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$User = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
if ($TaskName -eq "daily-paper-radar" -and (Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue)) {
    Unregister-ScheduledTask -TaskName $LegacyTaskName -Confirm:$false
    Write-Host "Removed legacy scheduled task $LegacyTaskName to avoid duplicate runs."
}
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "daily-paper-radar 每日论文日报" -Force | Out-Null
Write-Host "Installed $TaskName at $Time (computer local time). Runs while this user is logged in, including when locked."
