# Registers the hardware bridge scripts (OAK-1 camera, weighing scale, DTI
# gauge, and — where this station runs its own OCR to keep the load off the
# OH PC — the local OCR companion service) as Windows Scheduled Tasks that
# auto-start at logon and restart on failure. Run this in an ELEVATED
# PowerShell (Run as Administrator) — Register-ScheduledTask requires admin
# rights.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1
#   # On a PC other than the one running the backend (e.g. a second hangar
#   # PC with its own scale/DTI wired in but sharing the central database) —
#   # -Station MUST be different from every other PC's, or every browser tab
#   # on any PC receives every PC's scale/DTI readings indiscriminately
#   # (weighing/DTI both scope readings by station, defaulting to "1"):
#   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1 -Server http://172.146.5.98 -Station 2
#   # If the scale or DTI gauge landed on a different COM port on this PC than
#   # the defaults below, verify with: python -m serial.tools.list_ports
#   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1 -WeighingPort COM3 -DtiPort COM4

param(
    [string]$Server = "http://localhost",  # backend address the weighing/DTI bridges and OCR service push/forward to
    [string]$Station = "1",                # must be unique per PC — see usage note above
    [string]$WeighingPort = "COM3",        # the scale's actual COM port on THIS PC — verify with: python -m serial.tools.list_ports
    [string]$DtiPort = "COM4"              # the DTI gauge's actual COM port on THIS PC — verify with: python -m serial.tools.list_ports
)

$ErrorActionPreference = "Stop"

$py = "C:\Users\ADMIN\AppData\Local\Python\bin\pythonw.exe"   # windowless — python.exe would pop a visible console
$oak1Py = "C:\blade-rocking\scripts\oak1-venv\Scripts\pythonw.exe"   # depthai (OAK-1 SDK) only lives in this dedicated venv, not in $py
$ocrPy = "C:\blade-rocking\scripts\ocr-venv\Scripts\pythonw.exe"     # paddleocr only lives in this dedicated venv, not in $py or oak1-venv
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

# This PC has exactly one scale wired to it (iScale-BT-91, pinned to
# -WeighingPort) — weighing_bridge.py just opens that one COM port directly,
# no Bluetooth MAC discovery involved, so nothing else (e.g. iScale-BT-0111,
# now moved to the HPTR PC) can ever be picked up here even if it's in
# Bluetooth range.
# -WeighingPort/-DtiPort default to COM3/COM4, but those are just where the
# scale/gauge happened to land on the OH PC — it's a per-PC Bluetooth
# pairing assignment, not a constant, and can collide on a different PC
# (that happened on the HPTR PC: iScale-BT-91 and the DTI gauge both ended
# up enumerated under COM4, and only one process can hold a COM port at a
# time — the two bridges fought over it instead of either working reliably).
# Verify the actual assignment on THIS PC before registering:
#   python -m serial.tools.list_ports -v
Register-BridgeTask -Name "BladeRocking-OAK1CameraService" -ScriptArgs "oak1_camera_service.py" -Execute $oak1Py
Register-BridgeTask -Name "BladeRocking-WeighingBridge"     -ScriptArgs "weighing_bridge.py --port $WeighingPort --station $Station --server $Server"
Register-BridgeTask -Name "BladeRocking-DTIBridge"          -ScriptArgs "dti_bridge.py --port $DtiPort --station $Station --server $Server"
# Only meaningful on a station set up to run its own OCR model locally
# instead of sending scans to the OH PC (see hptr_ocr_service.py and
# CLAUDE.md's "Secondary Hardware Stations" section) — harmless to register
# elsewhere, but the task will silently stay dead if scripts\ocr-venv wasn't
# created (same failure mode as the OAK-1 task's venv, see CLAUDE.md).
Register-BridgeTask -Name "BladeRocking-HPTROCRService"     -ScriptArgs "hptr_ocr_service.py --server $Server" -Execute $ocrPy

Write-Host ""
Write-Host "Starting all four now (instead of waiting for next logon)..."
Start-ScheduledTask -TaskName "BladeRocking-OAK1CameraService"
Start-ScheduledTask -TaskName "BladeRocking-WeighingBridge"
Start-ScheduledTask -TaskName "BladeRocking-DTIBridge"
Start-ScheduledTask -TaskName "BladeRocking-HPTROCRService"

Start-Sleep -Seconds 5
Get-ScheduledTask -TaskName "BladeRocking-*" | Select-Object TaskName, State
