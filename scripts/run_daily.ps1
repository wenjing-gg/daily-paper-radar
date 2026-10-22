param(
    [string]$Python = "python",
    [string]$Profile = "",
    [string]$StateDir = "",
    [switch]$Check,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
# 任务计划程序可能持有旧环境；补充当前账户的持久用户环境变量。
$UserVariables = [Environment]::GetEnvironmentVariables("User")
foreach ($Name in $UserVariables.Keys) {
    if ($Name -ne "Path") {
        [Environment]::SetEnvironmentVariable($Name, $UserVariables[$Name], "Process")
    }
}
$Root = Split-Path $PSScriptRoot -Parent
$Arguments = @((Join-Path $PSScriptRoot "run_daily.py"))
if ($Profile) { $Arguments += @("--profile", $Profile) }
if ($StateDir) { $Arguments += @("--state-dir", $StateDir) }
if ($Check) { $Arguments += "--check" }
if ($DryRun) { $Arguments += "--dry-run" }
$env:PYTHONUTF8 = "1"
& $Python @Arguments
exit $LASTEXITCODE
