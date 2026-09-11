# Registers the three hardware bridge scripts (OAK-1 camera, weighing scale,
# DTI gauge) as Windows Scheduled Tasks that auto-start at logon and restart
# on failure. Run this in an ELEVATED PowerShell (Run as Administrator) —
# Register-ScheduledTask requires admin rights.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1
#   # On a PC other than the one running the backend (e.g. a second hangar
#   # PC with its own scale/DTI wired in but sharing the central database):
#   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1 -Server http://172.146.5.98

param(
    [string]$Server = "http://localhost"   # backend address the weighing/DTI bridges push readings to
)

$ErrorActionPreference = "Stop"

$py = "C:\Users\ADMIN\AppData\Local\Python\bin\pythonw.exe"   # windowless — python.exe would pop a visible console
$oak1Py = "C:\blade-rocking\scripts\oak1-venv\Scripts\pythonw.exe"   # depthai (OAK-1 SDK) only lives in this dedicated venv, not in $py
$scriptsDir = "C:\blade-rocking\scripts"

function Register-BridgeTask {
    param($Name, $ScriptArgs, $Execute = $py)

    $action = New-ScheduledTaskAction -Execute $Execute -Argument $ScriptArgs -WorkingDirectory $scriptsDir
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

# Two iScale scales share the OH station (iScale-BT-91, MAC 0025020126B1, and
# iScale-BT-0111, MAC 00250201225E) but only one is ever powered on at a time.
# weighing_bridge.py auto-discovers whichever one is live by Bluetooth MAC
# (see KNOWN_SCALES in that script) rather than a hard-coded COM port, so a
# single task covers both — no --port needed, and no action required when
# Windows reassigns a COM letter after a re-pair.
# COM4 is unconfirmed for the Sylvac DTI gauge — if it doesn't connect,
# re-pair the gauge in Windows Bluetooth settings and check its actual COM
# port with: python -m serial.tools.list_ports
Register-BridgeTask -Name "BladeRocking-OAK1CameraService" -ScriptArgs "oak1_camera_service.py" -Execute $oak1Py
Register-BridgeTask -Name "BladeRocking-WeighingBridge"     -ScriptArgs "weighing_bridge.py --server $Server"
Register-BridgeTask -Name "BladeRocking-DTIBridge"          -ScriptArgs "dti_bridge.py --port COM4 --station 1 --server $Server"

Write-Host ""
Write-Host "Starting all three now (instead of waiting for next logon)..."
Start-ScheduledTask -TaskName "BladeRocking-OAK1CameraService"
Start-ScheduledTask -TaskName "BladeRocking-WeighingBridge"
Start-ScheduledTask -TaskName "BladeRocking-DTIBridge"

Start-Sleep -Seconds 5
Get-ScheduledTask -TaskName "BladeRocking-*" | Select-Object TaskName, State
