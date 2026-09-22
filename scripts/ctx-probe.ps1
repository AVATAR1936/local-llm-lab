# ctx-probe.ps1 - find the largest context window that still fits fully on the GPU
# Run AFTER setting "Prefer No Sysmem Fallback" in the NVIDIA control panel.
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\ctx-probe.ps1"

$models = @(
    "qwen3.5:9b",
    "gemma4:12b",
    "uamarchuan/lapa-v0.1.2-instruct:Q4_K_M"
)
$ctxSizes = @(8192, 16384, 32768, 65536, 131072)

$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$csv   = "D:\Local Cluster\ctx_probe_$stamp.csv"
$txt   = "D:\Local Cluster\ctx_probe_$stamp.txt"

$prompt = "Перелічи три пункти порядку денного робочої зустрічі. Відповідай стисло."

function Get-GpuUsedMb {
    $v = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
    if ($v) { return [int]($v | Select-Object -First 1) }
    return -1
}

function Stop-AllModels {
    foreach ($m in $models) { & ollama stop $m 2>$null | Out-Null }
    Start-Sleep -Seconds 3
}

$rows = @()
$log  = @()
$log += "=== context probe: $stamp ==="
$log += "sysmem fallback must be DISABLED for these numbers to mean anything"
$log += ""

foreach ($m in $models) {
    foreach ($ctx in $ctxSizes) {

        Stop-AllModels
        $idle = Get-GpuUsedMb

        $body = @{
            model  = $m
            prompt = $prompt
            stream = $false
            options = @{
                num_ctx     = $ctx
                temperature = 0.2
                seed        = 42
                num_predict = 64
            }
        } | ConvertTo-Json -Depth 5

        Write-Host ("probing {0} @ num_ctx={1} ..." -f $m, $ctx) -ForegroundColor Cyan

        $status = "ok"; $tps = ""; $loadS = ""; $err = ""
        $t0 = Get-Date
        try {
            $r = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" `
                                   -Method Post -Body $body -ContentType "application/json" `
                                   -TimeoutSec 600
            if ($r.eval_count -and $r.eval_duration -gt 0) {
                $tps = [math]::Round($r.eval_count / ($r.eval_duration / 1e9), 1)
            }
            if ($r.load_duration) { $loadS = [math]::Round($r.load_duration / 1e9, 2) }
        } catch {
            $status = "FAIL"
            $err = ($_.Exception.Message -replace "\s+", " ")
            if ($err.Length -gt 160) { $err = $err.Substring(0,160) }
        }
        $wall = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)

        $peak = Get-GpuUsedMb
        $ps   = (& ollama ps 2>&1 | Out-String).Trim()

        $proc = "n/a"
        foreach ($line in ($ps -split "`n")) {
            if ($line -match [regex]::Escape($m)) {
                if     ($line -match "(\d+%\s*/\s*\d+%\s*CPU/GPU)") { $proc = $Matches[1] }
                elseif ($line -match "(100%\s*GPU)")                { $proc = "100% GPU" }
                elseif ($line -match "(100%\s*CPU)")                { $proc = "100% CPU" }
            }
        }

        $rows += [pscustomobject]@{
            model       = $m
            num_ctx     = $ctx
            status      = $status
            processor   = $proc
            gpu_idle_mb = $idle
            gpu_peak_mb = $peak
            kv_delta_mb = $(if ($peak -ge 0 -and $idle -ge 0) { $peak - $idle } else { "" })
            gen_tok_s   = $tps
            load_s      = $loadS
            wall_s      = $wall
            error       = $err
        }

        $log += ("{0} @ {1,6} -> {2,-4} {3,-16} gpu {4} MB (idle {5}) {6} tok/s {7}" -f `
                 $m, $ctx, $status, $proc, $peak, $idle, $tps, $err)

        if ($status -eq "FAIL") {
            $log += ("  stop climbing for {0}: ceiling passed" -f $m)
            break
        }
        if ($proc -ne "100% GPU" -and $proc -ne "n/a") {
            $log += ("  stop climbing for {0}: spilled to CPU" -f $m)
            break
        }
    }
    $log += ""
}

Stop-AllModels

$rows | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
$log  | Set-Content -Path $txt -Encoding UTF8

Write-Host ""
$rows | Format-Table model, num_ctx, status, processor, gpu_peak_mb, kv_delta_mb, gen_tok_s -AutoSize
Write-Output ""
Write-Output "csv: $csv"
Write-Output "log: $txt"
