# Read-only collector for Windows PowerShell 5.1+. Run manually on an authorized test VM.
# This is an inventory report, not a remote access agent. ESU requires separate verification.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$computer = Get-CimInstance Win32_ComputerSystem
$systemVolume = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
$currentVersion = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$edition = switch ($currentVersion.EditionID) {
    'Core' { 'Home' }
    'CoreN' { 'Home' }
    'CoreSingleLanguage' { 'Home' }
    'Professional' { 'Pro' }
    'ProfessionalN' { 'Pro' }
    default { 'Unknown' }
}
$ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    Select-Object -First 1 -ExpandProperty IPAddress
$report = [ordered]@{
    name = $env:COMPUTERNAME
    os_family = 'Windows'
    os_version = $(if ([int]$os.BuildNumber -ge 22000) { '11' } else { '10' })
    os_release = [string]$currentVersion.DisplayVersion
    os_edition = $edition
    os_build = "$($os.BuildNumber).$($currentVersion.UBR)"
    cpu = [string]$cpu.Name
    ram_gb = [int][math]::Round($computer.TotalPhysicalMemory / 1GB)
    disk_gb = [int][math]::Round($systemVolume.Size / 1GB)
    ip_address = $(if ($ip) { [string]$ip } else { $null })
}
# Refuse to replace an existing report; keep output on the machine until an operator copies it.
$json = $report | ConvertTo-Json -Depth 3
$stream = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::CreateNew)
try {
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false))
    $writer.Write($json)
    $writer.Flush()
} finally {
    if ($writer) { $writer.Dispose() } else { $stream.Dispose() }
}
Write-Host 'Raport zapisany. Nie wykonano zmian konfiguracji systemu ani weryfikacji ESU.'
