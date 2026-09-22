# diag2.ps1 - name the culprit of the original HTTP 400, and check text integrity properly
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\diag2.ps1"

[Net.ServicePointManager]::Expect100Continue = $false
$uri   = "http://localhost:11434/api/generate"
$model = "qwen3.5:9b"
$long  = Get-Content "D:\Local Cluster\data\transcripts\lecture_long_65min.txt" -Raw -Encoding UTF8

function Try-Request {
    param($Payload, [switch]$Compress, [string]$Body)   # Body = "string" | "bytes"

    $json = if ($Compress) { $Payload | ConvertTo-Json -Depth 5 -Compress }
            else           { $Payload | ConvertTo-Json -Depth 5 }
    try {
        if ($Body -eq "string") {
            $r = Invoke-RestMethod -Uri $uri -Method Post -Body $json `
                                   -ContentType "application/json" -TimeoutSec 900
        } else {
            $b = [System.Text.Encoding]::UTF8.GetBytes($json)
            $r = Invoke-RestMethod -Uri $uri -Method Post -Body $b `
                                   -ContentType "application/json; charset=utf-8" -TimeoutSec 900
        }
        return @{ ok = $true; r = $r; detail = "" }
    } catch {
        $d = $_.Exception.Message
        if ($_.Exception.Response) {
            try { $d = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd().Trim() } catch {}
        }
        if ($d.Length -gt 200) { $d = $d.Substring(0,200) }
        return @{ ok = $false; r = $null; detail = ($d -replace "\s+"," ") }
    }
}

Write-Host "=== A. four combinations on the full 44k transcript ===" -ForegroundColor Cyan
$base = @{ model = $model; prompt = $long; stream = $false
           options = @{ num_ctx = 32768; temperature = 0.2; seed = 42; num_predict = 1 } }

foreach ($body in @("string","bytes")) {
    foreach ($comp in @($true,$false)) {
        $res = if ($comp) { Try-Request -Payload $base -Compress -Body $body }
               else       { Try-Request -Payload $base -Body $body }
        "{0,-6} compress={1,-5} -> {2} {3}" -f $body, $comp,
            $(if ($res.ok) { "OK tokens=$($res.r.prompt_eval_count)" } else { "FAIL" }), $res.detail
    }
}

Write-Host ""
Write-Host "=== B. integrity, with thinking switched off and a real output budget ===" -ForegroundColor Cyan
$probe = "Їжак з'їв ґроно, є ще їжа."
foreach ($body in @("string","bytes")) {
    $p = @{ model = $model
            prompt = "Повтори наступний рядок дослівно, без змін і без пояснень: $probe"
            stream = $false
            think  = $false
            options = @{ num_ctx = 4096; temperature = 0.2; seed = 42; num_predict = 200 } }
    $res = Try-Request -Payload $p -Compress -Body $body
    if ($res.ok) {
        $echo = ($res.r.response -replace "\s+"," ").Trim()
        $think = ($res.r.thinking -replace "\s+"," ").Trim()
        $intact = ($echo -like "*Їжак*") -and ($echo -like "*з'їв*") -and ($echo -like "*ґроно*")
        "{0,-6} sent   : {1}" -f $body, $probe
        "{0,-6} got    : {1}" -f "", $echo
        if ($think) { "{0,-6} thought: {1}" -f "", $think.Substring(0,[Math]::Min(120,$think.Length)) }
        "{0,-6} verdict: {1}" -f "", $(if ($intact) { "TEXT INTACT" } else { "TEXT DAMAGED or empty" })
    } else {
        "{0,-6} FAIL {1}" -f $body, $res.detail
    }
    ""
}

Write-Host "=== C. does think=false actually stop the reasoning ===" -ForegroundColor Cyan
foreach ($t in @($true,$false)) {
    $p = @{ model = $model; prompt = "Скільки буде 17 + 25? Відповідай лише числом."
            stream = $false; think = $t
            options = @{ num_ctx = 4096; temperature = 0.2; seed = 42; num_predict = 300 } }
    $res = Try-Request -Payload $p -Compress -Body "bytes"
    if ($res.ok) {
        $thinkLen = if ($res.r.thinking) { $res.r.thinking.Length } else { 0 }
        "think={0,-5} answer='{1}'  thinking_chars={2}  eval_count={3}" -f `
            $t, ($res.r.response -replace "\s+"," ").Trim(), $thinkLen, $res.r.eval_count
    } else {
        "think={0,-5} FAIL {1}" -f $t, $res.detail
    }
}
