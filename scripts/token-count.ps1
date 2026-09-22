# token-count.ps1 - how many tokens each model actually needs for our transcripts
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\token-count.ps1"
#
# Uses prompt_eval_count from the Ollama API: the exact number of tokens the model
# read. num_predict = 1 so almost nothing is generated and the run stays short.

$models = @(
    "qwen3.5:9b",
    "gemma4:12b",
    "uamarchuan/lapa-v0.1.2-instruct:Q4_K_M"
)
$files = @(
    "D:\Local Cluster\data\transcripts\lecture_short_16min.txt",
    "D:\Local Cluster\data\transcripts\lecture_long_65min.txt"
)

$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$csv   = "D:\Local Cluster\token_count_$stamp.csv"
$rows  = @()

foreach ($f in $files) {
    if (-not (Test-Path $f)) { Write-Host "MISSING: $f" -ForegroundColor Red; continue }
    $text  = Get-Content $f -Raw -Encoding UTF8
    $chars = $text.Length

    foreach ($m in $models) {
        foreach ($x in $models) { & ollama stop $x 2>$null | Out-Null }
        Start-Sleep -Seconds 2

        $body = @{
            model   = $m
            prompt  = $text
            stream  = $false
            options = @{ num_ctx = 32768; temperature = 0.2; seed = 42; num_predict = 1 }
        } | ConvertTo-Json -Depth 5

        Write-Host ("{0}  <-  {1}" -f $m, (Split-Path $f -Leaf)) -ForegroundColor Cyan

        $tok = ""; $status = "ok"; $err = ""; $ppsec = ""
        try {
            $r = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" `
                                   -Method Post -Body $body -ContentType "application/json" `
                                   -TimeoutSec 900
            $tok = $r.prompt_eval_count
            if ($r.prompt_eval_duration -gt 0) {
                $ppsec = [math]::Round($tok / ($r.prompt_eval_duration / 1e9), 1)
            }
        } catch {
            $status = "FAIL"
            $err = ($_.Exception.Message -replace "\s+", " ")
            if ($err.Length -gt 160) { $err = $err.Substring(0,160) }
        }

        $ps = (& ollama ps 2>&1 | Out-String)
        $proc = if ($ps -match "100%\s*GPU") { "100% GPU" }
                elseif ($ps -match "(\d+%\s*/\s*\d+%\s*CPU/GPU)") { $Matches[1] }
                else { "n/a" }

        $rows += [pscustomobject]@{
            file            = Split-Path $f -Leaf
            chars           = $chars
            model           = $m
            status          = $status
            prompt_tokens   = $tok
            chars_per_token = $(if ($tok) { [math]::Round($chars / $tok, 2) } else { "" })
            pct_of_32k      = $(if ($tok) { [math]::Round(100 * $tok / 32768, 1) } else { "" })
            processor       = $proc
            prompt_tok_s    = $ppsec
            error           = $err
        }
    }
}

foreach ($x in $models) { & ollama stop $x 2>$null | Out-Null }

$rows | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
Write-Host ""
$rows | Format-Table file, chars, model, prompt_tokens, chars_per_token, pct_of_32k, processor -AutoSize
Write-Output ""
Write-Output "csv: $csv"
