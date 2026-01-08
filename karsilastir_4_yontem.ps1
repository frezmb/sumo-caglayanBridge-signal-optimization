param(
  [int[]]$Seeds = @(1,2,3,42),
  [switch]$ShowTable,
  [string]$CsvPath,
  [string]$RunsDir = ".\runs"
)

# PowerShell 5.1 uyumlu: ?? ve ?: operatörleri kullanılmadı.

if([string]::IsNullOrWhiteSpace($CsvPath)){
  $CsvPath = ".\karsilastirma_4yontem.csv"
}
function Get-LatestKosuMetricsPath {
  param([string]$BaseDir)

  if(-not (Test-Path $BaseDir)){ return $null }

  $latestKosu = Get-ChildItem $BaseDir -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^kosu_\d+$' } |
    Sort-Object { [int]($_.Name -replace 'kosu_','') } -Descending |
    Select-Object -First 1

  if(-not $latestKosu){ return $null }

  $m = Join-Path $latestKosu.FullName "metrics.json"
  if(Test-Path $m){ return $m }

  return $null
}

function Read-Json([string]$Path){
  if([string]::IsNullOrWhiteSpace($Path)){ return $null }
  if(-not (Test-Path -LiteralPath $Path)){ return $null }
  try {
    return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Get-Prop($obj, [string]$name){
  if($null -eq $obj){ return $null }
  $p = $obj.PSObject.Properties[$name]
  if($null -eq $p){ return $null }
  return $p.Value
}

function To-Double($v, [int]$round=2){
  if($null -eq $v){ return $null }
  try { return [math]::Round([double]$v, $round) } catch { return $null }
}

function To-Int($v){
  if($null -eq $v){ return $null }
  try { return [int]$v } catch { return $null }
}

function To-RelPath([string]$Path){
  if([string]::IsNullOrWhiteSpace($Path)){ return $null }
  try { $full = (Resolve-Path -LiteralPath $Path).Path } catch { 
    try { $full = [IO.Path]::GetFullPath($Path) } catch { return $Path }
  }
  $pwd = (Get-Location).Path
  if($full.StartsWith($pwd, [StringComparison]::OrdinalIgnoreCase)){
    $rel = $full.Substring($pwd.Length).TrimStart('\','/')
    return (".\" + $rel)
  }
  return $full
}

function First-ExistingPath([string[]]$Candidates){
  foreach($c in $Candidates){
    if([string]::IsNullOrWhiteSpace($c)){ continue }
    if(Test-Path -LiteralPath $c){
      try { return (Resolve-Path -LiteralPath $c).Path } catch { return $c }
    }
  }
  return $null
}

function Find-MetricsPath([string]$algo, [int]$seed){
  $cand = @()
  switch($algo){
    "temel" {
      $cand += (Join-Path $RunsDir "01_temel_seed$seed\kosu_001\metrics.json")
      $cand += (Join-Path $RunsDir "01_temel_seed$seed\metrics.json")
    }
    "kural" {
      $cand += (Join-Path $RunsDir "02_kural_seed$seed\kosu_001\metrics.json")
      $cand += (Join-Path $RunsDir "02_kural_seed$seed\kosu_001\kosu_001\metrics.json")
      $cand += (Join-Path $RunsDir "02_kural_seed$seed\metrics.json")
    }
    "pso" {
      $base = Join-Path $RunsDir "03_pso_replay_best_s$seed"
      $mLatest = Get-LatestKosuMetricsPath $base
      if($mLatest){ $cand += $mLatest }
      $cand += (Join-Path $RunsDir "03_pso_replay_best_s$seed\metrics.json")
    }

    "psoai" {
      $base = Join-Path $RunsDir "04_ai_pso_replay_best_s$seed"
      $mLatest = Get-LatestKosuMetricsPath $base
      if($mLatest){ $cand += $mLatest }
      $cand += (Join-Path $RunsDir "04_ai_pso_replay_best_s$seed\metrics.json")
    }

  }

  $p = First-ExistingPath $cand
  if($p){ return $p }

  # Yedek arama (nadiren gerek)
  try {
    $pattern = "$algo"
    if($algo -eq "psoai"){ $pattern = "ai_pso" }

    $seedRe = "(?i)(seed|_s)$seed(?!\d)"
      $hits = Get-ChildItem -LiteralPath $RunsDir -Recurse -File -Filter "metrics.json" -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match $seedRe -and $_.FullName -match $pattern } |
      Select-Object -First 50

    if($hits){ return $hits.FullName }
  } catch {}
  return $null
}

function Find-NetPathFromMetrics([string]$metricsPath){
  if([string]::IsNullOrWhiteSpace($metricsPath)){ return $null }
  $dir = Split-Path -Parent $metricsPath
  $cand = Join-Path $dir "net.xml"
  if(Test-Path -LiteralPath $cand){ return $cand }
  try {
    $net = Get-ChildItem -LiteralPath $dir -Recurse -File -Filter "net.xml" -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if($net){ return $net.FullName }
  } catch {}
  return $null
}

function Build-MethodRow([string]$algo, [int]$seed){
  $mPath = Find-MetricsPath $algo $seed
  $mObj  = Read-Json $mPath

  $wait = To-Double (Get-Prop $mObj "meanWaitingTime") 2
  $co2  = To-Double (Get-Prop $mObj "co2_total_abs") 3
  $tel  = To-Int    (Get-Prop $mObj "teleports")
  $end  = To-Int    (Get-Prop $mObj "ended")

  $netPath = $null
  if($algo -in @("pso","psoai")){
    $netPath = Find-NetPathFromMetrics $mPath
  }

  return [pscustomobject]@{
    algo = $algo
    wait = $wait
    co2  = $co2
    tel  = $tel
    ended = $end
    metricsPath = (To-RelPath $mPath)
    netPath     = (To-RelPath $netPath)
  }
}

function Join-Winners([object[]]$items){
  if(-not $items -or $items.Count -eq 0){ return $null }
  ($items | ForEach-Object { $_.algo.ToUpper() }) -join " = "
}

function Winner-ByWaitNoTeleport([object[]]$methods){
  $valid = $methods | Where-Object { $_.wait -ne $null -and $_.tel -eq 0 }
  if(-not $valid){ return $null }
  $min = ($valid | Measure-Object -Property wait -Minimum).Minimum
  $winners = $valid | Where-Object { $_.wait -eq $min }
  return (Join-Winners $winners)
}

function Winner-ByTeleportEnded([object[]]$methods){
  $valid = $methods | Where-Object { $_.tel -ne $null }
  if(-not $valid){ return $null }
  $minTel = ($valid | Measure-Object -Property tel -Minimum).Minimum
  $topTel = $valid | Where-Object { $_.tel -eq $minTel }

  $hasEnded = ($topTel | Where-Object { $_.ended -ne $null }).Count -gt 0
  if($hasEnded){
    $maxEnd = ($topTel | Measure-Object -Property ended -Maximum).Maximum
    $topTel = $topTel | Where-Object { $_.ended -eq $maxEnd }
  }

  $hasWait = ($topTel | Where-Object { $_.wait -ne $null }).Count -gt 0
  if($hasWait){
    $minWait = ($topTel | Measure-Object -Property wait -Minimum).Minimum
    $topTel = $topTel | Where-Object { $_.wait -eq $minWait }
  }
  return (Join-Winners $topTel)
}

function Winner-ByCO2NoTeleport([object[]]$methods){
  $valid = $methods | Where-Object { $_.co2 -ne $null -and $_.tel -eq 0 }
  if(-not $valid){ return $null }
  $min = ($valid | Measure-Object -Property co2 -Minimum).Minimum
  $winners = $valid | Where-Object { $_.co2 -eq $min }
  return (Join-Winners $winners)
}

function Points-ByRank([object[]]$methods, [string]$prop, [switch]$HigherBetter){
  $out = @{}
  foreach($m in $methods){ $out[$m.algo] = 0 }

  $vals = $methods | Where-Object { (Get-Prop $_ $prop) -ne $null } | ForEach-Object {
    [pscustomobject]@{ algo=$_.algo; val=(Get-Prop $_ $prop) }
  }
  if(-not $vals){ return $out }

  if($HigherBetter){
    $uniq = ($vals | Sort-Object val -Descending | Select-Object -ExpandProperty val -Unique)
  } else {
    $uniq = ($vals | Sort-Object val | Select-Object -ExpandProperty val -Unique)
  }

  $n = $methods.Count
  for($i=0; $i -lt $uniq.Count; $i++){
    $v = $uniq[$i]
    $rank = $i + 1
    $pts = [math]::Max(0, ($n - $rank + 1))
    ($vals | Where-Object { $_.val -eq $v }).algo | ForEach-Object { $out[$_] = $pts }
  }
  return $out
}

$rows = foreach($seed in $Seeds){
  $mTemel = Build-MethodRow "temel" $seed
  $mKural = Build-MethodRow "kural" $seed
  $mPSO   = Build-MethodRow "pso"   $seed
  $mAI    = Build-MethodRow "psoai" $seed

  $methods = @($mTemel,$mKural,$mPSO,$mAI)

  $wWait = Winner-ByWaitNoTeleport $methods
  $wTelE = Winner-ByTeleportEnded  $methods
  $wCO2  = Winner-ByCO2NoTeleport  $methods

  $ptsWait = Points-ByRank $methods "wait"
  $ptsCO2  = Points-ByRank $methods "co2"
  $ptsTel  = Points-ByRank $methods "tel"

  $pTemel = $ptsWait["temel"] + $ptsCO2["temel"] + $ptsTel["temel"]
  $pKural = $ptsWait["kural"] + $ptsCO2["kural"] + $ptsTel["kural"]
  $pPSO   = $ptsWait["pso"]   + $ptsCO2["pso"]   + $ptsTel["pso"]
  $pAI    = $ptsWait["psoai"] + $ptsCO2["psoai"] + $ptsTel["psoai"]

  $maxP = @($pTemel,$pKural,$pPSO,$pAI) | Measure-Object -Maximum | Select-Object -ExpandProperty Maximum
  $wP = @()
  if($pTemel -eq $maxP){ $wP += $mTemel }
  if($pKural -eq $maxP){ $wP += $mKural }
  if($pPSO   -eq $maxP){ $wP += $mPSO }
  if($pAI    -eq $maxP){ $wP += $mAI }
  $winnerPoints = Join-Winners $wP

  [pscustomobject]@{
    Seed = $seed

    Temel_Wait = $mTemel.wait
    Kural_Wait = $mKural.wait
    PSO_Wait   = $mPSO.wait
    PSOAI_Wait = $mAI.wait
    Kazanan_Wait_NoTeleport = $wWait

    Temel_Tel  = $mTemel.tel
    Kural_Tel  = $mKural.tel
    PSO_Tel    = $mPSO.tel
    PSOAI_Tel  = $mAI.tel
    Temel_Ended = $mTemel.ended
    Kural_Ended = $mKural.ended
    PSO_Ended   = $mPSO.ended
    PSOAI_Ended = $mAI.ended
    Kazanan_TelEnded = $wTelE

    Temel_CO2 = $mTemel.co2
    Kural_CO2 = $mKural.co2
    PSO_CO2   = $mPSO.co2
    PSOAI_CO2 = $mAI.co2
    Kazanan_CO2_NoTeleport = $wCO2

    Puan_Temel = $pTemel
    Puan_Kural = $pKural
    Puan_PSO   = $pPSO
    Puan_PSOAI = $pAI
    Kazanan_Puan = $winnerPoints

    Temel_Path = $mTemel.metricsPath
    Kural_Path = $mKural.metricsPath
    PSO_Path   = $mPSO.metricsPath
    PSOAI_Path = $mAI.metricsPath
    PSO_Net    = $mPSO.netPath
    PSOAI_Net  = $mAI.netPath
  }
}

# CSV üret
$csvDir = Split-Path -Parent $CsvPath
if(-not [string]::IsNullOrWhiteSpace($csvDir) -and -not (Test-Path -LiteralPath $csvDir)){
  New-Item -ItemType Directory -Path $csvDir | Out-Null
}
$rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Delimiter ';' -Path $CsvPath
Write-Host ("CSV yazildi: " + (To-RelPath $CsvPath)) -ForegroundColor Green

if($ShowTable){
  Write-Host ""
  Write-Host "== Ortalama Bekleme (s) ==" -ForegroundColor Cyan
  $rows | Select-Object Seed,Temel_Wait,Kural_Wait,PSO_Wait,PSOAI_Wait,Kazanan_Wait_NoTeleport |
    Format-Table -AutoSize | Out-Host

  Write-Host ""
  Write-Host "== Teleport / Ended ==" -ForegroundColor Cyan
  $rows | Select-Object Seed,Temel_Tel,Temel_Ended,Kural_Tel,Kural_Ended,PSO_Tel,PSO_Ended,PSOAI_Tel,PSOAI_Ended,Kazanan_TelEnded |
    Format-Table -AutoSize | Out-Host

  Write-Host ""
  Write-Host "== CO2 (abs) ==" -ForegroundColor Cyan
  $rows | Select-Object Seed,
      @{n="Temel_CO2_M";e={[math]::Round(($_.Temel_CO2/1e6),2)}},
      @{n="Kural_CO2_M";e={[math]::Round(($_.Kural_CO2/1e6),2)}},
      @{n="PSO_CO2_M";e={[math]::Round(($_.PSO_CO2/1e6),2)}},
      @{n="PSOAI_CO2_M";e={[math]::Round(($_.PSOAI_CO2/1e6),2)}},
      Kazanan_CO2_NoTeleport |
    Format-Table -AutoSize | Out-Host

  Write-Host ""
  Write-Host "== Toplam Puan (wait + CO2 + teleport) ==" -ForegroundColor Cyan
  $rows | Select-Object Seed,Puan_Temel,Puan_Kural,Puan_PSO,Puan_PSOAI,Kazanan_Puan |
    Format-Table -AutoSize | Out-Host
}

$rows
