# verify.ps1 - reproducibility + the temperature hypothesis, on gemma4 only
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\verify.ps1"

[Net.ServicePointManager]::Expect100Continue = $false
$uri   = "http://localhost:11434/api/generate"
$model = "gemma4:12b"

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

$questions = @{
    "lecture_short_16min.txt" = "Яку дату призначено для фінального екзамену з цієї дисципліни?"
    "lecture_long_65min.txt"  = "Яка політика щодо плагіату і які санкції вона передбачає?"
}

$files  = @("lecture_short_16min.txt", "lecture_long_65min.txt")
$temps  = @(0.2, 1.0)
$seeds  = @(42, 1234)

$stamp  = Get-Date -Format "yyyy-MM-dd_HH-mm"
$outDir = "D:\Local Cluster\out\verify"
$csv    = "D:\Local Cluster\verify_$stamp.csv"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Gpu { $v = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
               if ($v) { [int]($v | Select-Object -First 1) } else { -1 } }

function Ask {
    param([string]$Prompt, [double]$Temp, [int]$Seed, [int]$Predict)
    $json = @{ model = $model; prompt = $Prompt; stream = $false; think = $false
               options = @{ num_ctx = 32768; temperature = $Temp; top_p = 0.9; top_k = 40
                            repeat_penalty = 1.0; seed = $Seed; num_predict = $Predict }
             } | ConvertTo-Json -Depth 5 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        $r = Invoke-RestMethod -Uri $uri -Method Post -Body $bytes `
                               -ContentType "application/json; charset=utf-8" -TimeoutSec 1800
        return @{ ok = $true; text = $r.response; inTok = $r.prompt_eval_count
                  outTok = $r.eval_count
                  tps = $(if ($r.eval_duration -gt 0) { [math]::Round($r.eval_count/($r.eval_duration/1e9),1) } else { "" }) }
    } catch {
        $msg = $_.Exception.Message; $body = ""
        if ($_.Exception.Response) {
            try { $body = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd().Trim() } catch {}
        }
        return @{ ok = $false; text = ""; inTok = ""; outTok = ""; tps = ""
                  detail = (("msg='$msg' body='$body'" -replace "\s+"," ")) }
    }
}

$rows = @(); $n = 0; $total = ($files.Count * $temps.Count * $seeds.Count) + ($files.Count * $temps.Count)

foreach ($f in $files) {
    $text = Get-Content (Join-Path "D:\Local Cluster\data\transcripts" $f) -Raw -Encoding UTF8
    $short = $f -replace "^lecture_","" -replace "\.txt$",""

    foreach ($temp in $temps) {
        foreach ($seed in $seeds) {
            $n++
            & ollama stop $model 2>$null | Out-Null; Start-Sleep -Seconds 4
            $idle = Gpu
            Write-Host ("[{0}/{1}] protocol t={2} seed={3} {4}" -f $n,$total,$temp,$seed,$short) -ForegroundColor Cyan
            $r = Ask -Prompt ($PROTOCOL_PROMPT + "`n" + $text) -Temp $temp -Seed $seed -Predict 3000
            $name = "protocol__t{0}__s{1}__{2}.md" -f ($temp -replace "\.","_"), $seed, $short
            if ($r.text) { Set-Content -Path (Join-Path $outDir $name) -Value $r.text -Encoding UTF8 }
            $rows += [pscustomobject]@{ task="protocol"; file=$short; temperature=$temp; seed=$seed
                                        status=$(if($r.ok){"ok"}else{"FAIL"}); out_tokens=$r.outTok
                                        gen_tok_s=$r.tps; gpu_idle_mb=$idle; gpu_peak_mb=(Gpu)
                                        out_file=$name; error=$r.detail }
            $rows | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
        }
    }

    foreach ($temp in $temps) {
        $n++
        & ollama stop $model 2>$null | Out-Null; Start-Sleep -Seconds 4
        Write-Host ("[{0}/{1}] refusal t={2} {3}" -f $n,$total,$temp,$short) -ForegroundColor Cyan
        $p = "Нижче стенограма. Дай відповідь на питання, спираючись ЛИШЕ на стенограму.`n" +
             "Якщо відповіді в стенограмі немає, напиши рівно: НЕМАЄ ДАНИХ - і більше нічого.`n`n" +
             "ПИТАННЯ: " + $questions[$f] + "`n`nСТЕНОГРАМА:`n" + $text
        $r = Ask -Prompt $p -Temp $temp -Seed 42 -Predict 400
        $name = "refusal__t{0}__{1}.md" -f ($temp -replace "\.","_"), $short
        if ($r.text) { Set-Content -Path (Join-Path $outDir $name) -Value $r.text -Encoding UTF8 }
        $rows += [pscustomobject]@{ task="refusal"; file=$short; temperature=$temp; seed=42
                                    status=$(if($r.ok){"ok"}else{"FAIL"}); out_tokens=$r.outTok
                                    gen_tok_s=$r.tps; gpu_idle_mb=""; gpu_peak_mb=""
                                    out_file=$name; error=$r.detail }
        $rows | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
    }
}

& ollama stop $model 2>$null | Out-Null
Write-Host ""
$rows | Format-Table task, file, temperature, seed, status, out_tokens, gen_tok_s -AutoSize
Write-Output "csv:     $csv"
Write-Output "outputs: $outDir"
