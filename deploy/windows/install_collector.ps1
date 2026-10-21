# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         deploy/windows/install_collector.ps1
# Date:         21-10-2026
# Description:  Runs the collector as a scheduled task: starts at logon, restarted within 5 min if it stops.
# Usage:        powershell -ExecutionPolicy Bypass -File deploy\windows\install_collector.ps1 [-Uninstall]
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"

$TaskName = "GTFS collector"
$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
if ($Uninstall) {
    Write-Output "collector task removed"
    exit 0
}

$Action = New-ScheduledTaskAction -Execute "$Repo\venv\Scripts\python.exe" `
    -Argument "-m gtfs_position_collection" -WorkingDirectory $Repo
# Start at logon, then try again every 5 minutes; a run already going is left alone
# (MultipleInstances IgnoreNew), so a collector that stopped is back within 5 minutes.
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)).Repetition
# No 3-day time limit (the default), and keep running on battery.
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "collector task installed and started: $TaskName"
Write-Output "status: Get-ScheduledTask -TaskName '$TaskName' | Select-Object State"
