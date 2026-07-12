# Registers the three hardware bridge scripts (OAK-1 camera, weighing scale,
# DTI gauge) as Windows Scheduled Tasks that auto-start at logon and restart
# on failure. Run this in an ELEVATED PowerShell (Run as Administrator) —
# Register-ScheduledTask requires admin rights.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1

$ErrorActionPreference = "Stop"

$py = "C:\Users\ADMIN\AppData\Local\Python\bin\python.exe"
$scriptsDir = "C:\blade-rocking\scripts"

function Register-BridgeTask {
    param($Name, $ScriptArgs)

    $action = New-ScheduledTaskAction -Execute $py -Argument $ScriptArgs -WorkingDirectory $scriptsDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $trigger.Delay = "PT20S"   # give Bluetooth/USB stack time to settle after logon
    $settings = New-ScheduledTaskSettingsSet `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "Registered: $Name"
}

# COM3 confirmed as the iScale-BT-91 weighing scale (Bluetooth MAC 0025020126B1
# matches its PnP instance ID). COM4 is unconfirmed for the Sylvac DTI gauge —
# if it doesn't connect, re-pair the gauge in Windows Bluetooth settings and
# check its actual COM port with: python -m serial.tools.list_ports
Register-BridgeTask -Name "BladeRocking-OAK1CameraService" -ScriptArgs "oak1_camera_service.py"
Register-BridgeTask -Name "BladeRocking-WeighingBridge"     -ScriptArgs "weighing_bridge.py --port COM3 --server http://localhost"
Register-BridgeTask -Name "BladeRocking-DTIBridge"          -ScriptArgs "dti_bridge.py --port COM4 --station 1 --server http://localhost"

Write-Host ""
Write-Host "Starting all three now (instead of waiting for next logon)..."
Start-ScheduledTask -TaskName "BladeRocking-OAK1CameraService"
Start-ScheduledTask -TaskName "BladeRocking-WeighingBridge"
Start-ScheduledTask -TaskName "BladeRocking-DTIBridge"

Start-Sleep -Seconds 5
Get-ScheduledTask -TaskName "BladeRocking-*" | Select-Object TaskName, State
