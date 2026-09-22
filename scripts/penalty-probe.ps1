# penalty-probe.ps1 - чи винен repeat_penalty у вересневій проблемі
# Run:  powershell -ExecutionPolicy Bypass -File "D:\Local Cluster\scripts\penalty-probe.ps1"

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

$files    = @("lecture_short_16min.txt","lecture_long_65min.txt")
$penalties = @(1.0, 1.1, 1.3)

$stamp  = Get-Date -Format "yyyy-MM-dd_HH-mm"
$outDir = "D:\Local Cluster\out\penalty"
$csv    = "D:\Local Cluster\results\penalty_$stamp.csv"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Gpu { $v = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
               if ($v) { [int]($v | Select-Object -First 1) } else { -1 } }

$rows = @(); $n = 0; $total = $files.Count * $penalties.Count
foreach ($f in $files) {
    $text  = Get-Content (Join-Path "D:\Local Cluster\data\transcripts" $f) -Raw -Encoding UTF8
    $short = $f -replace "^lecture_","" -replace "\.txt$",""
    foreach ($rp in $penalties) {
        $n++
        & ollama stop $model 2>$null | Out-Null; Start-Sleep -Seconds 4
        $idle = Gpu
        Write-Host ("[{0}/{1}] repeat_penalty={2}  {3}" -f $n,$total,$rp,$short) -ForegroundColor Cyan

        $json = @{ model = $model; prompt = ($PROTOCOL_PROMPT + "`n" + $text)
                   stream = $false; think = $false
                   options = @{ num_ctx = 32768; temperature = 0.2; top_p = 0.9; top_k = 40
                                repeat_penalty = $rp; seed = 42; num_predict = 3000 }
                 } | ConvertTo-Json -Depth 5 -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)

        $status="ok"; $detail=""; $resp=""; $outTok=""; $tps=""
        $t0 = Get-Date
        try {
            $r = Invoke-RestMethod -Uri $uri -Method Post -Body $bytes `
                                   -ContentType "application/json; charset=utf-8" -TimeoutSec 1800
            $resp = $r.response; $outTok = $r.eval_count
            if ($r.eval_duration -gt 0) { $tps = [math]::Round($r.eval_count/($r.eval_duration/1e9),1) }
        } catch {
            $status="FAIL"; $msg=$_.Exception.Message; $body=""
            if ($_.Exception.Response) {
                try { $body = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd().Trim() } catch {}
            }
            $detail = ("msg='$msg' body='$body'" -replace "\s+"," ")
        }
        $wall = [math]::Round(((Get-Date)-$t0).TotalSeconds,1)

        $name = "protocol__rp{0}__{1}.md" -f ($rp -replace "\.","_"), $short
        if ($resp) { Set-Content -Path (Join-Path $outDir $name) -Value $resp -Encoding UTF8 }

        $rows += [pscustomobject]@{ file=$short; repeat_penalty=$rp; status=$status
                                    out_tokens=$outTok; gen_tok_s=$tps; wall_s=$wall
                                    gpu_idle_mb=$idle; gpu_peak_mb=(Gpu)
                                    out_file=$name; error=$detail }
        $rows | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
    }
}
& ollama stop $model 2>$null | Out-Null
Write-Host ""
$rows | Format-Table file, repeat_penalty, status, out_tokens, gen_tok_s, wall_s -AutoSize
Write-Output "csv:     $csv"
Write-Output "outputs: $outDir"
