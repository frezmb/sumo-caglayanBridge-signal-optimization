param(
  [Parameter(Mandatory=$true)]
  [ValidateSet("temel","kural","pso","psoai")]
  [string]$Algo,

  [int]$Seed = 42,
  [int]$Begin = 0,
  [int]$End   = 2160
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$cfg = Join-Path $root "aktif\aktif.sumocfg"
if(!(Test-Path $cfg)){ throw "aktif.sumocfg yok: $cfg" }

function Need-Net($a){
  return ($a -eq "pso" -or $a -eq "psoai")
}

function Get-NetPath([string]$a, [int]$s){
  if($a -eq "pso"){
    return Join-Path $root ("runs\03_pso_replay_best_s{0}\kosu_001\net.xml" -f $s)
  }
  if($a -eq "psoai"){
    return Join-Path $root ("runs\04_ai_pso_replay_best_s{0}\kosu_001\net.xml" -f $s)
  }
  return $null
}

$net = $null
if(Need-Net $Algo){
  $net = Get-NetPath $Algo $Seed
  if(!(Test-Path $net)){
    throw ("net.xml bulunamadi: Algo={0} Seed={1} (beklenen: {2})" -f $Algo,$Seed,$net)
  }
}

# Komut
$args = @(
  "-c", $cfg,
  "--begin", $Begin,
  "--end", $End,
  "--seed", $Seed,
  "--no-step-log", "true"
)

if($net){
  $args += @("--net-file", $net)
}

Write-Host ("CALISIYOR: sumo-gui {0}" -f ($args -join " ")) -ForegroundColor Yellow
& sumo-gui @args
