# token-count2.ps1 - verified token counts for both transcripts on all three models
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\token-count2.ps1"
#
# Three parts:
#   1. integrity check - does the Ukrainian text survive the trip, per transfer method
#   2. blame check     - was Expect:100-continue the cause of the earlier HTTP 400
#   3. the actual counts, using the method that passed part 1

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
$txt   = "D:\Local Cluster\token_count_$stamp.txt"
$out   = @()

function Send-Ollama {
    param([string]$Model, [string]$Prompt, [int]$Predict = 1, [string]$Method = "bytes")

    $payload = @{
        model   = $Model
        prompt  = $Prompt
        stream  = $false
        options = @{ num_ctx = 32768; temperature = 0.2; top_p = 0.9; top_k = 40;
                     seed = 42; repeat_penalty = 1.0; num_predict = $Predict }
    }
    $json = $payload | ConvertTo-Json -Depth 5 -Compress

    try {
        if ($Method -eq "string") {
            $r = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                                   -Body $json -ContentType "application/json" -TimeoutSec 900
        } else {
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
            $r = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                                   -Body $bytes -ContentType "application/json; charset=utf-8" `
                                   -TimeoutSec 900
        }
        return @{ ok = $true; tokens = $r.prompt_eval_count; text = $r.response; detail = "" }
    }
    catch {
        $detail = $_.Exception.Message
        $resp = $_.Exception.Response
        if ($resp) {
            try { $detail = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd().Trim() } catch { }
        }
        if ($detail.Length -gt 200) { $detail = $detail.Substring(0,200) }
        return @{ ok = $false; tokens = ""; text = ""; detail = ($detail -replace "\s+"," ") }
    }
}

# ---------- 1. integrity ----------
# A phrase with the letters that break first when the encoding is wrong: і ї є ґ and an apostrophe.
$probe  = "Їжак з'їв ґроно,є ще їжа."
$marker = "ЇЖАК"
$out += "=== 1. integrity of the text in transit ==="
[Net.ServicePointManager]::Expect100Continue = $false
foreach ($mth in @("string","bytes")) {
    $r = Send-Ollama -Model $models[0] `
                     -Prompt ("Повтори наступний рядок дослівно, без жодних змін і без пояснень: " + $probe) `
                     -Predict 40 -Method $mth
    $echo = ($r.text -replace "\s+"," ").Trim()
    $intact = $echo -like "*з'їв*" -and $echo -like "*ґроно*" -and $echo -like "*Їжак*"
    $out += ("{0,-7} sent: {1}" -f $mth, $probe)
    $out += ("{0,-7} got : {1}" -f "", $echo)
    $out += ("{0,-7} verdict: {1}" -f "", $(if ($intact) { "TEXT INTACT" } else { "TEXT DAMAGED" }))
    $out += ""
}

# ---------- 2. who caused the 400 ----------
$out += "=== 2. was Expect:100-continue the culprit ==="
$long = Get-Content $files[1] -Raw -Encoding UTF8
foreach ($expect in @($true, $false)) {
    [Net.ServicePointManager]::Expect100Continue = $expect
    $r = Send-Ollama -Model $models[0] -Prompt $long -Predict 1 -Method "bytes"
    $out += ("Expect100Continue = {0,-5} -> {1} {2}" -f $expect,
             $(if ($r.ok) { "OK tokens=$($r.tokens)" } else { "FAIL" }), $r.detail)
}
[Net.ServicePointManager]::Expect100Continue = $false
$out += ""

# ---------- 3. the counts ----------
$out += "=== 3. token counts (utf8 byte body) ==="
$rows = @()
foreach ($f in $files) {
    $text  = Get-Content $f -Raw -Encoding UTF8
    $chars = $text.Length
    foreach ($m in $models) {
        foreach ($x in $models) { & ollama stop $x 2>$null | Out-Null }
        Start-Sleep -Seconds 2
        Write-Host ("{0}  <-  {1}" -f $m, (Split-Path $f -Leaf)) -ForegroundColor Cyan
        $r = Send-Ollama -Model $m -Prompt $text -Predict 1 -Method "bytes"
        $rows += [pscustomobject]@{
            file            = Split-Path $f -Leaf
            chars           = $chars
            model           = $m
            status          = $(if ($r.ok) { "ok" } else { "FAIL" })
            prompt_tokens   = $r.tokens
            chars_per_token = $(if ($r.tokens) { [math]::Round($chars / $r.tokens, 2) } else { "" })
            pct_of_32k      = $(if ($r.tokens) { [math]::Round(100 * $r.tokens / 32768, 1) } else { "" })
            error           = $r.detail
        }
    }
}
foreach ($x in $models) { & ollama stop $x 2>$null | Out-Null }

$rows | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
$out += ($rows | Format-Table file, chars, model, prompt_tokens, chars_per_token, pct_of_32k -AutoSize | Out-String)
$out | Set-Content -Path $txt -Encoding UTF8

Write-Host ""
$out | ForEach-Object { Write-Output $_ }
Write-Output "csv: $csv"
Write-Output "log: $txt"
