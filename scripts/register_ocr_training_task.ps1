# Registers the weekly OCR retraining cycle as a Windows Scheduled Task.
# Separate from register_bridge_tasks.ps1 because this is a weekly trigger
# at a fixed time, not an at-logon-forever one like the hardware bridges.
# Run this in an ELEVATED PowerShell (Run as Administrator) —
# Register-ScheduledTask requires admin rights.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File register_ocr_training_task.ps1

$ErrorActionPreference = "Stop"

# Dedicated training venv (Python 3.11 — PaddlePaddle/PaddleOCR don't
# support the system's default Python 3.14), NOT the same interpreter the
# hardware bridges use.
$py = "C:\blade-rocking\backend\finetune\.venv-train\Scripts\pythonw.exe"
$workingDir = "C:\blade-rocking\backend\finetune"
$script = "run_weekly_cycle.py"

$action = New-ScheduledTaskAction -Execute $py -Argument $script -WorkingDirectory $workingDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "10:00PM"
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit ([TimeSpan]::FromHours(6)) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "BladeRocking-OCRWeeklyRetrain" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered: BladeRocking-OCRWeeklyRetrain (every Saturday 22:00)"
Get-ScheduledTask -TaskName "BladeRocking-OCRWeeklyRetrain" | Select-Object TaskName, State
