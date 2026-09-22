# token-diag.ps1 - find out WHY the token-count request returns 400
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\token-diag.ps1"

[Net.ServicePointManager]::Expect100Continue = $false

$model = "qwen3.5:9b"
$file  = "D:\Local Cluster\data\transcripts\lecture_short_16min.txt"
$text  = Get-Content $file -Raw -Encoding UTF8

Write-Host ("PowerShell: {0}" -f $PSVersionTable.PSVersion) -ForegroundColor Yellow
Write-Host ("text length: {0} chars" -f $text.Length) -ForegroundColor Yellow
Write-Host ""

function Invoke-Ollama {
    param([string]$Prompt, [string]$Method)

    $payload = @{
        model   = $model
        prompt  = $Prompt
        stream  = $false
        options = @{ num_ctx = 32768; temperature = 0.2; seed = 42; num_predict = 1 }
    }
    $json = $payload | ConvertTo-Json -Depth 5 -Compress

    try {
        if ($Method -eq "string") {
            $r = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                                   -Body $json -ContentType "application/json" -TimeoutSec 600
        } else {
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
            $r = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                                   -Body $bytes -ContentType "application/json; charset=utf-8" `
                                   -TimeoutSec 600
        }
        return @{ ok = $true; tokens = $r.prompt_eval_count; detail = "" }
    }
    catch {
        $detail = $_.Exception.Message
        $resp = $_.Exception.Response
        if ($resp) {
            try {
                $sr = New-Object IO.StreamReader($resp.GetResponseStream())
                $bodyText = $sr.ReadToEnd()
                if ($bodyText) { $detail = $bodyText.Trim() }
            } catch { }
        }
        if ($detail.Length -gt 300) { $detail = $detail.Substring(0,300) }
        return @{ ok = $false; tokens = ""; detail = ($detail -replace "\s+"," ") }
    }
}

Write-Host "--- A. tiny prompt, both methods ---" -ForegroundColor Cyan
foreach ($mth in @("string","bytes")) {
    $res = Invoke-Ollama -Prompt "Привіт. Скажи одне слово." -Method $mth
    "{0,-7} tiny  -> {1} {2}" -f $mth, $(if($res.ok){"OK tokens=$($res.tokens)"}else{"FAIL"}), $res.detail
}

Write-Host ""
Write-Host "--- B. size ladder, string body ---" -ForegroundColor Cyan
foreach ($n in @(500, 2000, 5000, 8000, 12000, $text.Length)) {
    $n2 = [Math]::Min($n, $text.Length)
    $res = Invoke-Ollama -Prompt $text.Substring(0, $n2) -Method "string"
    "{0,7} chars -> {1} {2}" -f $n2, $(if($res.ok){"OK tokens=$($res.tokens)"}else{"FAIL"}), $res.detail
    if (-not $res.ok) { break }
}

Write-Host ""
Write-Host "--- C. size ladder, utf8 byte body ---" -ForegroundColor Cyan
foreach ($n in @(500, 2000, 5000, 8000, 12000, $text.Length)) {
    $n2 = [Math]::Min($n, $text.Length)
    $res = Invoke-Ollama -Prompt $text.Substring(0, $n2) -Method "bytes"
    "{0,7} chars -> {1} {2}" -f $n2, $(if($res.ok){"OK tokens=$($res.tokens)"}else{"FAIL"}), $res.detail
    if (-not $res.ok) { break }
}

Write-Host ""
Write-Host "--- D. first 300 chars of the file ---" -ForegroundColor Cyan
$text.Substring(0, [Math]::Min(300, $text.Length))

Write-Host ""
Write-Host "--- E. suspicious characters ---" -ForegroundColor Cyan
$ctrl = 0; $bad = @()
foreach ($ch in $text.ToCharArray()) {
    $code = [int]$ch
    if ($code -lt 32 -and $code -ne 9 -and $code -ne 10 -and $code -ne 13) {
        $ctrl++
        if ($bad.Count -lt 10) { $bad += ("U+{0:X4}" -f $code) }
    }
}
"control chars besides tab/CR/LF: $ctrl  $($bad -join ' ')"
"BOM at start: " + ($text[0] -eq [char]0xFEFF)
