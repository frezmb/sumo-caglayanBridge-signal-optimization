param(
  [ValidateSet("temel","kural","pso","psoai")]
  [string]$Algo = "psoai",
  [int]$Seed = 42
)

# Karşılaştırma scripti ile satırları çek
$rows = & .\karsilastir_4_yontem.ps1 -Seeds @($Seed)

$row = $rows | Where-Object { $_.Seed -eq $Seed } | Select-Object -First 1
if(-not $row){
  throw "Seed bulunamadı: $Seed"
}

# SUMO config
$cfg = ".\aktif\aktif.sumocfg"

# Algo'ya göre net.xml seç
$net = $null
switch ($Algo) {
  "pso"   { $net = $row.PSO_Net }
  "psoai" { $net = $row.PSOAI_Net }
  default { $net = $null } # temel/kural: config içindeki net kullanılır
}

# Komutu hazırla ve çalıştır
$args = @("-c", $cfg, "--seed", "$Seed", "--begin", "0", "--end", "2160", "--no-step-log", "true")
if($net){
  $args = @("-c", $cfg, "--net-file", $net, "--seed", "$Seed", "--begin", "0", "--end", "2160", "--no-step-log", "true")
}

Write-Host "CALISIYOR: sumo-gui $($args -join ' ')"
& sumo-gui @args
