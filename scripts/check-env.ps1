# check-env.ps1 - environment snapshot for Local Cluster
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\check-env.ps1"

$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$out   = "D:\Local Cluster\env_$stamp.txt"

function Line($t) { Write-Output $t }

$report = @()
$report += "=== Local Cluster environment snapshot: $stamp ==="
$report += ""

$report += "--- OLLAMA_MODELS variable ---"
$report += "process: $env:OLLAMA_MODELS"
$report += "user   : $([Environment]::GetEnvironmentVariable('OLLAMA_MODELS','User'))"
$report += "machine: $([Environment]::GetEnvironmentVariable('OLLAMA_MODELS','Machine'))"
$report += ""

$report += "--- other OLLAMA_* variables ---"
Get-ChildItem Env: | Where-Object { $_.Name -like "OLLAMA*" } | ForEach-Object {
    $report += ("{0} = {1}" -f $_.Name, $_.Value)
}
$report += ""

$report += "--- looking for model storage ---"
$candidates = @(
    "$env:USERPROFILE\.ollama\models",
    "D:\ollama\models",
    "D:\.ollama\models",
    "D:\Ollama\models"
)
foreach ($p in $candidates) {
    if (Test-Path $p) {
        $sz = (Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue |
               Measure-Object -Property Length -Sum).Sum
        $gb = [math]::Round($sz / 1GB, 2)
        $report += "FOUND  $p  ($gb GB)"
    } else {
        $report += "absent $p"
    }
}
$report += ""
$report += "--- any *ollama* folder on D ---"
$found = Get-ChildItem D:\ -Directory -Filter "*ollama*" -ErrorAction SilentlyContinue
if ($found) { $found | ForEach-Object { $report += $_.FullName } }
else        { $report += "(none in root of D)" }
$report += ""

$report += "--- ollama ---"
$report += "client: " + (& ollama --version 2>&1 | Out-String).Trim()
$report += (& ollama list 2>&1 | Out-String).Trim()
$report += ""

$report += "--- disk space ---"
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Name -in @('C','D') } | ForEach-Object {
    $free = [math]::Round($_.Free / 1GB, 1)
    $used = [math]::Round($_.Used / 1GB, 1)
    $report += ("{0}: free {1} GB, used {2} GB" -f $_.Name, $free, $used)
}
$report += ""

$report += "--- GPU (idle baseline) ---"
$report += (& nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv 2>&1 | Out-String).Trim()
$report += ""

$report += "--- runtimes ---"
$report += "docker: " + (& docker --version 2>&1 | Out-String).Trim()
$report += "git   : " + (& git --version 2>&1 | Out-String).Trim()
$report += "python: " + (& python --version 2>&1 | Out-String).Trim()

$report | Set-Content -Path $out -Encoding UTF8
$report | ForEach-Object { Line $_ }
Write-Output ""
Write-Output "saved to: $out"
