# Probes the TiQR server's /api/health. Each failed probe exits non-zero, so the task's last
# result shows it; once three probes fail in a row, a critical Application event is logged for
# the customer's monitoring to pick up. The Linux equivalent is tiqr-health.sh.
[CmdletBinding()]
param(
    # The data folder: the installer keeps the settings files and the database here.
    [string]$DataFolder = (Join-Path $env:ProgramData 'TiQR'),
    # Registers the every-minute task that runs this script as the TiQR service account, then exits.
    [switch]$Install
)

$ErrorActionPreference = 'Stop'
$TaskName = 'TiQR Health Probe'
$EventSource = 'TiQR-Health'
$FailuresBeforeAlert = 3
$StateFile = Join-Path $DataFolder 'health-failures.txt'

if ($Install) {
    # Writing to the event log needs a registered source, and only an administrator can register
    # one, so the install step does it for the probe.
    if (-not [System.Diagnostics.EventLog]::SourceExists($EventSource)) {
        New-EventLog -LogName Application -Source $EventSource
    }
    # The task runs this script where the installer copied it, and reads the data folder it is given.
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DataFolder `"$DataFolder`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
    $taskSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
        -MultipleInstances IgnoreNew -StartWhenAvailable
    # The server's own virtual account, not SYSTEM: it already reads the config and writes the data.
    $principal = New-ScheduledTaskPrincipal -UserId 'NT SERVICE\TiQR' -LogonType ServiceAccount
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $taskSettings -Principal $principal -Force | Out-Null
    exit 0
}

# The settings the server reads from the data folder, .env.local last so it wins. Each file is
# KEY=VALUE, the format systemd reads through EnvironmentFile; blank lines and comments skip.
$config = @{}
foreach ($file in '.env', '.env.local') {
    $path = Join-Path $DataFolder $file
    if (-not (Test-Path -LiteralPath $path)) { continue }
    foreach ($line in Get-Content -LiteralPath $path) {
        $text = $line.Trim()
        $split = $text.IndexOf('=')
        if ($split -lt 1 -or $text.StartsWith('#')) { continue }
        $key = $text.Substring(0, $split).Trim()
        $config[$key] = $text.Substring($split + 1).Trim().Trim('"', "'")
    }
}

# Probe the address the server binds to; a wildcard bind answers on loopback.
$bind = $config['TIQR_HOST']
if (-not $bind) { $bind = '127.0.0.1' }
switch ($bind) {
    '0.0.0.0' { $address = '127.0.0.1' }
    '::' { $address = '[::1]' }
    default { $address = if ($bind.Contains(':')) { "[$bind]" } else { $bind } }
}
$port = $config['TIQR_PORT']
if (-not $port) { $port = '7102' }
$scheme = 'http'
if ($config['TIQR_TLS_CERT']) {
    $scheme = 'https'
    # A self-signed certificate is fine for this loopback check; it proves liveness, not identity.
    $protocols = [System.Net.ServicePointManager]::SecurityProtocol
    [System.Net.ServicePointManager]::SecurityProtocol =
        $protocols -bor [System.Net.SecurityProtocolType]::Tls12
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
}
$url = "${scheme}://${address}:${port}/api/health"

function Write-Event($Id, $Type, $Message) {
    Write-EventLog -LogName Application -Source $EventSource -EventId $Id -EntryType $Type `
        -Message $Message
}

$previous = 0
if (Test-Path -LiteralPath $StateFile) {
    [void][int]::TryParse((Get-Content -LiteralPath $StateFile -Raw).Trim(), [ref]$previous)
}

try {
    Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 | Out-Null
} catch {
    $reason = $_.Exception.Message
    $count = $previous + 1
    Set-Content -LiteralPath $StateFile -Value $count
    if ($count -eq $FailuresBeforeAlert) {
        Write-Event 1 'Error' "TiQR health check failed $count times in a row: $url ($reason)"
    }
    Write-Output "TiQR health check failed: $url ($reason)"
    exit 1
}

Set-Content -LiteralPath $StateFile -Value 0
if ($previous -ge $FailuresBeforeAlert) {
    Write-Event 2 'Information' "TiQR answers again at $url after $previous failed checks"
}
exit 0
