# Marks the OH PC's plain-HTTP LAN origins as "secure" for Chrome/Edge so
# navigator.mediaDevices.getUserMedia() (the in-browser webcam fallback in
# CameraModal.tsx / CameraScanner.tsx) works there despite not being https.
# Without this, those origins are treated as insecure contexts and
# navigator.mediaDevices is undefined — see CLAUDE.md's "Secondary Hardware
# Stations" section.
#
# This does NOT touch OAK-1 stations — oak1_camera_service.py talks to
# localhost, which is already a secure context and unaffected either way.
# Use this only on stations that must fall back to the in-browser webcam
# (no OAK-1 attached).
#
# Run this in an ELEVATED PowerShell (Run as Administrator) on the STATION PC
# whose browser needs the fallback — not on the OH PC itself.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File allow_insecure_camera_origin.ps1
#   # extra/alternate origins, e.g. if the OH PC address ever changes:
#   powershell -ExecutionPolicy Bypass -File allow_insecure_camera_origin.ps1 -Origins "http://172.146.5.98","http://bladerocking-1-","http://newhost"

param(
    # Keep in sync with CORS_ORIGINS in .env.oh and DEFAULT_ORIGINS in
    # oak1_camera_service.py — all three must agree on the OH PC's address.
    [string[]]$Origins = @("http://172.146.5.98", "http://bladerocking-1-")
)

$ErrorActionPreference = "Stop"

function Set-InsecureOriginPolicy {
    param($PolicyRoot)

    if (-not (Test-Path $PolicyRoot)) {
        New-Item -Path $PolicyRoot -Force | Out-Null
    }
    $key = Join-Path $PolicyRoot "OverrideSecurityRestrictionsOnInsecureOrigin"
    New-Item -Path $key -Force | Out-Null
    for ($i = 0; $i -lt $Origins.Count; $i++) {
        New-ItemProperty -Path $key -Name "$($i + 1)" -Value $Origins[$i] -PropertyType String -Force | Out-Null
    }
    Write-Host "Set $key ->" ($Origins -join ", ")
}

Set-InsecureOriginPolicy -PolicyRoot "HKLM:\SOFTWARE\Policies\Google\Chrome"
Set-InsecureOriginPolicy -PolicyRoot "HKLM:\SOFTWARE\Policies\Microsoft\Edge"

Write-Host ""
Write-Host "Policy set for Chrome and Edge. Fully close all browser windows"
Write-Host "(check Task Manager for lingering chrome.exe/msedge.exe) and reopen"
Write-Host "for it to take effect."
Write-Host "Verify at chrome://policy or edge://policy — look for"
Write-Host "'OverrideSecurityRestrictionsOnInsecureOrigin' under Chrome/Edge policies with no errors."
