# diag3.ps1 - why does the full transcript fail now when it passed half an hour ago
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\diag3.ps1"

[Net.ServicePointManager]::Expect100Continue = $false
$uri   = "http://localhost:11434/api/generate"
$model = "qwen3.5:9b"
$long  = Get-Content "D:\Local Cluster\data\transcripts\lecture_long_65min.txt" -Raw -Encoding UTF8

function Gpu { $v = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
               if ($v) { [int]($v | Select-Object -First 1) } else { -1 } }

function Post {
    param([int]$Ctx, [string]$Prompt, [int]$Predict = 1)
    $json = @{ model = $model; prompt = $Prompt; stream = $false; think = $false
               options = @{ num_ctx = $Ctx; temperature = 0.2; seed = 42; num_predict = $Predict }
             } | ConvertTo-Json -Depth 5 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        $r = Invoke-RestMethod -Uri $uri -Method Post -Body $bytes `
                               -ContentType "application/json; charset=utf-8" -TimeoutSec 900
        return @{ ok = $true; tokens = $r.prompt_eval_count; detail = "" }
    } catch {
        # keep BOTH: the exception message and the response body, never let one erase the other
        $msg  = $_.Exception.Message
        $body = ""
        if ($_.Exception.Response) {
            try { $body = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd().Trim() } catch {}
            try { $code = [int]$_.Exception.Response.StatusCode } catch { $code = "?" }
        } else { $code = "no-http-response" }
        $d = "[$code] msg='$msg'"
        if ($body) { $d += " body='$body'" }
        if ($d.Length -gt 400) { $d = $d.Substring(0,400) }
        return @{ ok = $false; tokens = ""; detail = ($d -replace "\s+"," ") }
    }
}

Write-Host "=== state before anything ===" -ForegroundColor Cyan
"gpu used: $(Gpu) MB of 12282"
"ollama ps:"; (& ollama ps 2>&1 | Out-String).Trim()
"ollama version: " + ((& ollama --version 2>&1 | Out-String).Trim())
""

Write-Host "=== A. clean slate, then the full transcript at 32768 ===" -ForegroundColor Cyan
& ollama stop $model 2>$null | Out-Null
Start-Sleep -Seconds 3
"gpu after unload: $(Gpu) MB"
$r = Post -Ctx 32768 -Prompt $long
"result: " + $(if ($r.ok) { "OK tokens=$($r.tokens)" } else { "FAIL " + $r.detail })
"gpu after: $(Gpu) MB"
"ollama ps:"; (& ollama ps 2>&1 | Out-String).Trim()
""

Write-Host "=== B. same text, climbing the context ladder ===" -ForegroundColor Cyan
foreach ($ctx in @(16384, 20480, 24576, 32768)) {
    & ollama stop $model 2>$null | Out-Null
    Start-Sleep -Seconds 3
    $idle = Gpu
    $r = Post -Ctx $ctx -Prompt $long
    $peak = Gpu
    "num_ctx {0,6} idle {1,5} peak {2,5} -> {3}" -f $ctx, $idle, $peak,
        $(if ($r.ok) { "OK tokens=$($r.tokens)" } else { "FAIL " + $r.detail })
}
""

Write-Host "=== C. same context, growing the prompt ===" -ForegroundColor Cyan
foreach ($frac in @(0.25, 0.5, 0.75, 1.0)) {
    $n = [int]($long.Length * $frac)
    & ollama stop $model 2>$null | Out-Null
    Start-Sleep -Seconds 3
    $r = Post -Ctx 32768 -Prompt $long.Substring(0, $n)
    "{0,6} chars -> {1}" -f $n, $(if ($r.ok) { "OK tokens=$($r.tokens)" } else { "FAIL " + $r.detail })
    if (-not $r.ok) { break }
}

& ollama stop $model 2>$null | Out-Null
