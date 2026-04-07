# Opens inbound TCP 8000 for THIRAMAI (Windows Defender Firewall).
# Run PowerShell as Administrator if you get "Access is denied".
$ruleName = "Thiramai Dashboard 8000"
$existing = netsh advfirewall firewall show rule name="$ruleName" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Rule already exists: $ruleName"
    exit 0
}
netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=8000
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to add rule (try: Run as Administrator)."
    exit $LASTEXITCODE
}
Write-Host "Firewall rule added: $ruleName (TCP 8000 inbound)"
