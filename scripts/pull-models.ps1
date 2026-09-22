# pull-models.ps1 - download round-1 candidate models and record their specs
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\pull-models.ps1"

$models = @(
    "qwen3.5:9b",
    "gemma4:12b",
    "uamarchuan/lapa-v0.1.2-instruct:Q4_K_M"
)

$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$log   = "D:\Local Cluster\models_$stamp.txt"
$report = @()

$report += "=== round-1 candidate models: $stamp ==="
$report += "OLLAMA_MODELS = $env:OLLAMA_MODELS"
$report += "ollama client = " + (& ollama --version 2>&1 | Out-String).Trim()
$report += ""

foreach ($m in $models) {
    Write-Host ""
    Write-Host "=== pulling $m ===" -ForegroundColor Cyan
    $t0 = Get-Date
    & ollama pull $m
    $ok = $LASTEXITCODE -eq 0
    $secs = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)

    $report += "--- $m ---"
    if ($ok) {
        $report += "pull: OK in $secs s"
        $report += (& ollama show $m 2>&1 | Out-String).Trim()
    } else {
        $report += "pull: FAILED after $secs s (exit $LASTEXITCODE)"
    }
    $report += ""
}

$report += "--- ollama list ---"
$report += (& ollama list 2>&1 | Out-String).Trim()
$report += ""
$report += "--- disk D after pull ---"
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Name -eq 'D' } | ForEach-Object {
    $report += ("D: free {0} GB" -f [math]::Round($_.Free / 1GB, 1))
}

$report | Set-Content -Path $log -Encoding UTF8
Write-Host ""
Write-Host "=== summary ===" -ForegroundColor Green
$report | ForEach-Object { Write-Output $_ }
Write-Output ""
Write-Output "saved to: $log"
