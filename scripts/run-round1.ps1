# run-round1.ps1 - round 1: 3 models x 2 transcripts x 3 tasks
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\run-round1.ps1"

[Net.ServicePointManager]::Expect100Continue = $false
$uri = "http://localhost:11434/api/generate"

$models = @(
    @{ tag = "qwen35-9b";  name = "qwen3.5:9b" },
    @{ tag = "gemma4-12b"; name = "gemma4:12b" },
    @{ tag = "lapa-v012";  name = "uamarchuan/lapa-v0.1.2-instruct:Q4_K_M" }
)

$PROTOCOL_PROMPT = @"
Ти складаєш протокол зустрічі за стенограмою. Пиши українською.

Обов'язкові розділи, саме в цьому порядку:
1. Тема - один рядок.
2. Учасники - лише ті, хто справді говорив у стенограмі.
3. Згадані - люди, підрозділи й ролі, про яких говорили, але які не виступали.
4. Рішення - що вирішено, по пунктах.
5. Правила і цифри - усі бали, дати, строки, кількості, назви файлів, шаблонів і колонок, що прозвучали. Нічого не округлювати й не переформульовувати.
6. Питання без відповіді - те, що прозвучало, але не було вирішено.

Правила:
- Спирайся лише на стенограму. Нічого не додавай від себе.
- Якщо строк названо відносно ("наступного тижня"), запиши його так, як сказано, і постав "(?)".
- Якщо розділ порожній, напиши "немає".

СТЕНОГРАМА:
"@

$tasks = @(
    @{ file = "lecture_short_16min.txt"; task = "protocol"; predict = 3000; q = $null },
    @{ file = "lecture_short_16min.txt"; task = "q_answerable";   predict = 400
       q = "Що означають колонки «старт», «стоп» і «континію» у шаблоні ретроспективи?" },
    @{ file = "lecture_short_16min.txt"; task = "q_unanswerable"; predict = 400
       q = "Яку дату призначено для фінального екзамену з цієї дисципліни?" },
    @{ file = "lecture_long_65min.txt";  task = "protocol"; predict = 3000; q = $null },
    @{ file = "lecture_long_65min.txt";  task = "q_answerable";   predict = 400
       q = "Хто веде лабораторні роботи і як їх звати?" },
    @{ file = "lecture_long_65min.txt";  task = "q_unanswerable"; predict = 400
       q = "Яка політика щодо плагіату і які санкції вона передбачає?" }
)

$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$outDir = "D:\Local Cluster\out\round1"
$csv    = "D:\Local Cluster\round1_$stamp.csv"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Gpu { $v = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
               if ($v) { [int]($v | Select-Object -First 1) } else { -1 } }

$rows = @()
$total = $models.Count * $tasks.Count
$i = 0

foreach ($m in $models) {
    foreach ($t in $tasks) {
        $i++
        $text = Get-Content (Join-Path "D:\Local Cluster\data\transcripts" $t.file) -Raw -Encoding UTF8

        if ($t.task -eq "protocol") {
            $prompt = $PROTOCOL_PROMPT + "`n" + $text
        } else {
            $prompt = "Нижче стенограма. Дай відповідь на питання, спираючись ЛИШЕ на стенограму." + "`n" +
                      "Якщо відповіді в стенограмі немає, напиши рівно: НЕМАЄ ДАНИХ - і більше нічого." + "`n`n" +
                      "ПИТАННЯ: " + $t.q + "`n`n" + "СТЕНОГРАМА:`n" + $text
        }

        foreach ($x in $models) { & ollama stop $x.name 2>$null | Out-Null }
        Start-Sleep -Seconds 4
        $idle = Gpu

        Write-Host ("[{0}/{1}] {2} | {3} | {4}" -f $i, $total, $m.tag, $t.task, $t.file) -ForegroundColor Cyan

        $json = @{ model = $m.name; prompt = $prompt; stream = $false; think = $false
                   options = @{ num_ctx = 32768; temperature = 0.2; top_p = 0.9; top_k = 40
                                repeat_penalty = 1.0; seed = 42; num_predict = $t.predict }
                 } | ConvertTo-Json -Depth 5 -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)

        $status = "ok"; $detail = ""; $resp = ""
        $inTok = ""; $outTok = ""; $genTps = ""; $ppTps = ""
        $t0 = Get-Date
        try {
            $r = Invoke-RestMethod -Uri $uri -Method Post -Body $bytes `
                                   -ContentType "application/json; charset=utf-8" -TimeoutSec 1800
            $resp   = $r.response
            $inTok  = $r.prompt_eval_count
            $outTok = $r.eval_count
            if ($r.eval_duration -gt 0)        { $genTps = [math]::Round($r.eval_count / ($r.eval_duration/1e9), 1) }
            if ($r.prompt_eval_duration -gt 0) { $ppTps  = [math]::Round($r.prompt_eval_count / ($r.prompt_eval_duration/1e9), 1) }
        } catch {
            $status = "FAIL"
            $msg = $_.Exception.Message; $body = ""
            if ($_.Exception.Response) {
                try { $body = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd().Trim() } catch {}
            }
            $detail = ("msg='$msg' body='$body'" -replace "\s+"," ")
            if ($detail.Length -gt 300) { $detail = $detail.Substring(0,300) }
        }
        $wall = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
        $peak = Gpu

        $base = "{0}__{1}__{2}" -f $t.task, $m.tag, ($t.file -replace "\.txt$","")
        if ($resp) { Set-Content -Path (Join-Path $outDir "$base.md") -Value $resp -Encoding UTF8 }

        $rows += [pscustomobject]@{
            model = $m.tag; task = $t.task; file = $t.file; status = $status
            prompt_tokens = $inTok; out_tokens = $outTok
            prompt_tok_s = $ppTps; gen_tok_s = $genTps
            wall_s = $wall; gpu_idle_mb = $idle; gpu_peak_mb = $peak
            out_file = "$base.md"; error = $detail
        }
        $rows | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8   # save as we go
    }
}

foreach ($x in $models) { & ollama stop $x.name 2>$null | Out-Null }

Write-Host ""
$rows | Format-Table model, task, file, status, prompt_tokens, out_tokens, gen_tok_s, wall_s -AutoSize
Write-Output ""
Write-Output "csv:     $csv"
Write-Output "outputs: $outDir"
