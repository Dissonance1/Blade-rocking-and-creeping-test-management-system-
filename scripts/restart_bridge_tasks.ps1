# Restarts the hardware bridge Scheduled Tasks registered by
# register_bridge_tasks.ps1, without needing to re-run that (admin-only)
# registration script. Safe to run as a normal (non-elevated) user — starting
# and stopping an already-registered task doesn't need admin rights, only
# creating/removing one does.
#
# BladeRocking-DTIBridge is deliberately NOT restarted here: this station's
# DTI gauge (Sylvac S_Dial WORK) is BLE HID keyboard mode, not a COM-port
# bridge — dti_bridge.py can never produce a reading for it. See CLAUDE.md's
# "DTI gauge (Sylvac S_Dial WORK / SY289)" section under Secondary Hardware
# Stations. If that task still shows up below, it's registered but was never
# fully removed (Unregister-ScheduledTask needs an elevated PowerShell) —
# harmless left stopped, but run this from an admin prompt to remove it:
#   Unregister-ScheduledTask -TaskName "BladeRocking-DTIBridge" -Confirm:$false

$tasks = @(
    "BladeRocking-OAK1CameraService",
    "BladeRocking-WeighingBridge",
    "BladeRocking-HPTROCRService"
)

foreach ($name in $tasks) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Skipping $name (not registered on this PC)"
        continue
    }
    Write-Host "Restarting $name..."
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $name
}

Start-Sleep -Seconds 3
Write-Host ""
Get-ScheduledTask -TaskName "BladeRocking-*" | Select-Object TaskName, State | Format-Table -AutoSize
