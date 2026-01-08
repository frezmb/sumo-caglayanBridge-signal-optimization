# karsilastir_4_yontem.ps1 - 4 teknigin metrics.json degerlerini karsilastirir
# PowerShell 5.1 uyumlu

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

param(
  [int[]]$Seeds = @(42),
  [string]$RunDir = '.\\runs',
  [string]$CsvOut = '',
  [switch]$ShowTable
)

function To-Rel {
  param([string]$p)
  if (-not $p) { return $null }
  try {
    $full = (Resolve-Path -LiteralPath $p).Path
    $here = (Get-Location).Path
    if ($full.StartsWith($here, [System.StringComparison]::OrdinalIgnoreCase)) {
      return '.' + $full.Substring($here.Length)
    }
  } catch {}
  return $p
}

function Read-Json {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  try {
    return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Find-Metrics {
  param([string]$Dir,[string]$PreferRel)

  $prefer = if ($PreferRel) { Join-Path $Dir $PreferRel } else { $null }
  if ($prefer -and (Test-Path -LiteralPath $prefer)) { return $prefer }

  if (Test-Path -LiteralPath $Dir) {
    $g = Get-ChildItem -LiteralPath $Dir -Recurse -File -Filter 'metrics.json' -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 1
    if ($g) { return $g.FullName }
  }
  return $null
}

function Find-NetNearMetrics {
  param([string]$MetricsPath)
  if (-not $MetricsPath) { return $null }
  try {
    $dir = Split-Path -Path $MetricsPath -Parent
    $cand = Join-Path $dir 'net.xml'
    if (Test-Path -LiteralPath $cand) { return $cand }

    $g = Get-ChildItem -LiteralPath $dir -Recurse -File -Filter 'net.xml' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($g) { return $g.FullName }
  } catch {}
  return $null
}

function Safe-Round {
  param($x,[int]$d=2)
  if ($null -eq $x) { return $null }
  try { return [math]::Round([double]$x, $d) } catch { return $x }
}

function Pick-WinnerNoTeleport {
  param($temel,$kural,$pso,$psoai)

  $cands = @()
  if ($temel -and $temel.wait -ne $null) { $cands += $temel }
  if ($kural -and $kural.wait -ne $null) { $cands += $kural }
  if ($pso -and $pso.wait -ne $null) { $cands += $pso }
  if ($psoai -and $psoai.wait -ne $null) { $cands += $psoai }

  if ($cands.Count -eq 0) { return $null }

  $noTel = @($cands | Where-Object { $_.tel -eq 0 })
  $use = if ($noTel.Count -gt 0) { $noTel } else { $cands }

  $best = $use | Sort-Object @{Expression='tel'; Ascending=$true}, @{Expression='wait'; Ascending=$true} | Select-Object -First 1
  return $best.algo
}

$rows = foreach ($seed in $Seeds) {
  $seed = [int]$seed

  $temelM = Find-Metrics -Dir (Join-Path $RunDir ("01_temel_seed{0}" -f $seed)) -PreferRel 'kosu_001\\metrics.json'
  $kuralM = Find-Metrics -Dir (Join-Path $RunDir ("02_kural_seed{0}" -f $seed)) -PreferRel 'kosu_001\\metrics.json'
  $psoM   = Find-Metrics -Dir (Join-Path $RunDir ("03_pso_replay_best_s{0}" -f $seed)) -PreferRel 'kosu_001\\metrics.json'
  $aiM    = Find-Metrics -Dir (Join-Path $RunDir ("04_ai_pso_replay_best_s{0}" -f $seed)) -PreferRel 'kosu_001\\metrics.json'

  $temelJ = Read-Json -Path $temelM
  $kuralJ = Read-Json -Path $kuralM
  $psoJ   = Read-Json -Path $psoM
  $aiJ    = Read-Json -Path $aiM

  $temelWait = if ($temelJ) { $temelJ.meanWaitingTime } else { $null }
  $kuralWait = if ($kuralJ) { $kuralJ.meanWaitingTime } else { $null }
  $psoWait   = if ($psoJ)   { $psoJ.meanWaitingTime } else { $null }
  $aiWait    = if ($aiJ)    { $aiJ.meanWaitingTime } else { $null }

  $temelCO2 = if ($temelJ) { $temelJ.co2_total_abs } else { $null }
  $kuralCO2 = if ($kuralJ) { $kuralJ.co2_total_abs } else { $null }
  $psoCO2   = if ($psoJ)   { $psoJ.co2_total_abs } else { $null }
  $aiCO2    = if ($aiJ)    { $aiJ.co2_total_abs } else { $null }

  $temelTel = if ($temelJ) { $temelJ.teleports } else { $null }
  $kuralTel = if ($kuralJ) { $kuralJ.teleports } else { $null }
  $psoTel   = if ($psoJ)   { $psoJ.teleports } else { $null }
  $aiTel    = if ($aiJ)    { $aiJ.teleports } else { $null }

  $psoImpr = $null
  if ($kuralWait -ne $null -and [double]$kuralWait -ne 0 -and $psoWait -ne $null) {
    $psoImpr = Safe-Round (([double]$kuralWait - [double]$psoWait) / [double]$kuralWait * 100) 1
  }

  $aiImpr = $null
  if ($kuralWait -ne $null -and [double]$kuralWait -ne 0 -and $aiWait -ne $null) {
    $aiImpr = Safe-Round (([double]$kuralWait - [double]$aiWait) / [double]$kuralWait * 100) 1
  }

  $candTemel = [pscustomobject]@{ algo='temel'; wait=$temelWait; tel=($temelTel -ne $null ? [int]$temelTel : 999999); }
  $candKural = [pscustomobject]@{ algo='kural'; wait=$kuralWait; tel=($kuralTel -ne $null ? [int]$kuralTel : 999999); }
  $candPso   = [pscustomobject]@{ algo='pso';   wait=$psoWait;   tel=($psoTel -ne $null ? [int]$psoTel : 999999); }
  $candAi    = [pscustomobject]@{ algo='psoai'; wait=$aiWait;    tel=($aiTel -ne $null ? [int]$aiTel : 999999); }

  $winner = Pick-WinnerNoTeleport -temel $candTemel -kural $candKural -pso $candPso -psoai $candAi

  $psoNet = Find-NetNearMetrics -MetricsPath $psoM
  $aiNet  = Find-NetNearMetrics -MetricsPath $aiM

  [pscustomobject]@{
    Seed                   = $seed
    Temel_Wait             = Safe-Round $temelWait 2
    Kural_Wait             = Safe-Round $kuralWait 2
    PSO_Wait               = Safe-Round $psoWait 2
    PSOAI_Wait             = Safe-Round $aiWait 2

    Temel_CO2              = Safe-Round $temelCO2 3
    Kural_CO2              = Safe-Round $kuralCO2 3
    PSO_CO2                = Safe-Round $psoCO2 3
    PSOAI_CO2              = Safe-Round $aiCO2 3

    Temel_Tel              = $temelTel
    Kural_Tel              = $kuralTel
    PSO_Tel                = $psoTel
    PSOAI_Tel              = $aiTel

    PSO_Impr_vsKural_pct   = $psoImpr
    PSOAI_Impr_vsKural_pct = $aiImpr
    Kazanan_NoTeleport     = $winner

    Temel_Path             = To-Rel $temelM
    Kural_Path             = To-Rel $kuralM
    PSO_Path               = To-Rel $psoM
    PSOAI_Path             = To-Rel $aiM

    PSO_Net                = To-Rel $psoNet
    PSOAI_Net              = To-Rel $aiNet
  }
}

# CSV
if ([string]::IsNullOrWhiteSpace($CsvOut)) {
  $CsvOut = '.\\karsilastirma_4yontem.csv'
}

$rows | Export-Csv -Path $CsvOut -Delimiter ';' -NoTypeInformation -Encoding UTF8
Write-Host ("CSV yazildi: {0}" -f $CsvOut) -ForegroundColor Green

if ($ShowTable) {
  Write-Host "" 
  Write-Host "--- Bekleme + Teleport + Iyilesme ---" -ForegroundColor Cyan
  $rows |
    Select-Object Seed,Temel_Wait,Kural_Wait,PSO_Wait,PSOAI_Wait,Temel_Tel,Kural_Tel,PSO_Tel,PSOAI_Tel,PSO_Impr_vsKural_pct,PSOAI_Impr_vsKural_pct,Kazanan_NoTeleport |
    Format-Table -AutoSize

  Write-Host "" 
  Write-Host "--- CO2 (toplam) ---" -ForegroundColor Cyan
  $rows |
    Select-Object Seed,Temel_CO2,Kural_CO2,PSO_CO2,PSOAI_CO2 |
    Format-Table -AutoSize
}

# pipeline'a donsun
$rows
