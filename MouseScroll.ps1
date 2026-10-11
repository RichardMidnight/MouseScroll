# Function to check admin rights
function Test-IsAdmin {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Relaunch as admin if not already
if (-not (Test-IsAdmin)) {
    Write-Host "`n🛡️  This script needs to run as Administrator."
    Write-Host "⏫ Relaunching with elevated privileges..."
    Write-Host "`nPress any key to continue..."
    $x = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    Start-Process powershell -Verb runAs -ArgumentList ("-ExecutionPolicy Bypass -File `"" + $PSCommandPath + "`"")
    exit
}

# Prompt user
$choice = Read-Host "`nType 'mac' to enable reverse (Mac-style) scroll, or 'win' to restore Windows default scroll"

if ($choice -ne 'mac' -and $choice -ne 'win') {
    Write-Host "`n❌ Invalid input. Type 'mac' or 'win'."
    Write-Host "`nPress any key to exit..."
    $x = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

$value = if ($choice -eq 'mac') { 1 } else { 0 }

# Get HID mouse devices
$mouseDevices = Get-PnpDevice -Class Mouse | Where-Object { $_.InstanceId -like "HID*" }

foreach ($device in $mouseDevices) {
    $instanceId = $device.InstanceId
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Enum\$instanceId\Device Parameters"

    try {
        if (!(Test-Path $regPath)) {
            Write-Host "⚠️  Registry path not found for: $instanceId"
            continue
        }

        Set-ItemProperty -Path $regPath -Name FlipFlopWheel -Value $value -Force
        Write-Host "✔ FlipFlopWheel set to $value for: $instanceId"
    } catch {
        Write-Host "❌ Failed to update: $instanceId"
        Write-Host $_.Exception.Message
    }
}

Write-Host "`n✅ Done. Unplug and reconnect your mouse, or reboot to apply."
Write-Host "`nPress any key to exit..."
$x = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
