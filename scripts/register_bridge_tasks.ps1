# Registers the hardware bridge scripts (OAK-1 camera, weighing scale, and —
# where this station runs its own OCR to keep the load off the OH PC — the
# local OCR companion service) as Windows Scheduled Tasks that auto-start at
# logon and restart on failure. Run this in an ELEVATED PowerShell (Run as
# Administrator) — Register-ScheduledTask requires admin rights.
#
# dti_bridge.py is NOT registered by this script — see the note above the
# Register-BridgeTask calls below for why (the deployed DTI gauge is BLE HID
# keyboard mode, not a COM-port bridge). -DtiPort is kept as a param only for
# a future station with a genuine classic-SPP/RS-232 gauge to wire back up.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1
#   # On a PC other than the one running the backend (e.g. a second hangar
#   # PC with its own scale wired in but sharing the central database) —
#   # -Station MUST be different from every other PC's, or every browser tab
#   # on any PC receives every PC's scale readings indiscriminately
#   # (weighing scopes readings by station, defaulting to "1"):
#   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1 -Server http://172.146.5.98 -Station 2
#   # If the scale landed on a different COM port on this PC than the default
#   # below, verify with: python -m serial.tools.list_ports
#   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1 -WeighingPort COM3

param(
    [string]$Server = "http://localhost",  # backend address the weighing bridge and OCR service push/forward to
    [string]$Station = "1",                # must be unique per PC — see usage note above
    [string]$WeighingPort = "COM3",        # the scale's actual COM port on THIS PC — verify with: python -m serial.tools.list_ports
    [string]$DtiPort = "COM4"              # unused unless a future station re-adds a genuine classic-SPP/RS-232 DTI gauge — see note above
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
# -WeighingPort defaults to COM3, but that's just where the scale happened to
# land on the OH PC — it's a per-PC Bluetooth pairing assignment, not a
# constant. Verify the actual assignment on THIS PC before registering:
#   python -m serial.tools.list_ports -v
#
# dti_bridge.py is NOT registered here. It only applies to a DTI gauge that's
# genuinely classic Bluetooth SPP (or wired RS-232) and binds to a raw COM
# port. The Sylvac S_Dial WORK gauge actually deployed is BLE-only and runs
# in Bluetooth HID keyboard mode instead — no COM port, no bridge process, no
# -Station/--station tagging; see CLAUDE.md's "DTI gauge (Sylvac S_Dial WORK /
# SY289)" section under Secondary Hardware Stations. If a future station gets
# a genuine classic-SPP/RS-232 DTI gauge, add its own
# Register-BridgeTask/Start-ScheduledTask call back for that PC only — do not
# reintroduce it here unconditionally, it can never work for the HId gauge
# and previously fought weighing_bridge.py over a shared COM port.
Register-BridgeTask -Name "BladeRocking-OAK1CameraService" -ScriptArgs "oak1_camera_service.py" -Execute $oak1Py
Register-BridgeTask -Name "BladeRocking-WeighingBridge"     -ScriptArgs "weighing_bridge.py --port $WeighingPort --station $Station --server $Server"
# Only meaningful on a station set up to run its own OCR model locally
# instead of sending scans to the OH PC (see hptr_ocr_service.py and
# CLAUDE.md's "Secondary Hardware Stations" section) — harmless to register
# elsewhere, but the task will silently stay dead if scripts\ocr-venv wasn't
# created (same failure mode as the OAK-1 task's venv, see CLAUDE.md).
Register-BridgeTask -Name "BladeRocking-HPTROCRService"     -ScriptArgs "hptr_ocr_service.py --server $Server --station $Station" -Execute $ocrPy

Write-Host ""
Write-Host "Starting all three now (instead of waiting for next logon)..."
Start-ScheduledTask -TaskName "BladeRocking-OAK1CameraService"
Start-ScheduledTask -TaskName "BladeRocking-WeighingBridge"
Start-ScheduledTask -TaskName "BladeRocking-HPTROCRService"

Start-Sleep -Seconds 5
Get-ScheduledTask -TaskName "BladeRocking-*" | Select-Object TaskName, State
