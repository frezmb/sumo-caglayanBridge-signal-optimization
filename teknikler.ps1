param(
  # Komut satırından şunların hepsini kabul eder:
  # -Seeds 2,7,13,21,42,77,101,123
  # -Seeds "2 7 13 21 42 77 101 123"
  # -Seeds @(2,7,13,21,42,77,101,123)
  [string[]]$Seeds = @("2,7,13,21,42,77,101,123"),

  [switch]$ShowTable,

  [string]$CsvPath = ".\karsilastirma_perseed_progress.csv"
)

function Parse-Seeds([string[]]$raw) {
  $txt = ($raw -join ",")
  $list = $txt -split '[,; \t]+' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ }
  # uniq + sıralı
  $list | Sort-Object -Unique
}

$seedList = Parse-Seeds $Seeds
if(-not $seedList.Count){
  throw "Seed listesi boş. Örn: -Seeds 2,7,13,21,42,77,101,123"
}

Write-Host "Istenen seedler: $($seedList -join ',')" -ForegroundColor Cyan

# 4 teknik için gerekli dosyalar var mı kontrol et
function Is-ReadySeed([int]$s){
  $paths = @(
    ".\runs\01_temel_seed$s\kosu_001\metrics.json",
    ".\runs\02_kural_seed$s\kosu_001\metrics.json",
    ".\runs\03_pso_replay_best_s$s\kosu_001\metrics.json",
    ".\runs\04_ai_pso_replay_best_s$s\kosu_001\metrics.json"  # BayesianPSO publish buraya geliyorsa OK
  )
  foreach($p in $paths){
    if(-not (Test-Path $p)){ return $false }
  }
  return $true
}

$ready = @()
foreach($s in $seedList){
  if(Is-ReadySeed $s){ $ready += $s }
}

$readyStr = if($ready.Count){ ($ready -join ",") } else { "-" }
Write-Host "Hazir seedler (4 teknik var): $readyStr" -ForegroundColor Green

if($ready.Count -eq 0){
  Write-Host "Hazir seed yok. (runs klasorunde 4 teknigin metrics.json'lari eksik olabilir.)" -ForegroundColor Yellow
  Write-Host "Yine de teknik menusu acilacak; ama karsilastirma kismi bos kalabilir." -ForegroundColor Yellow
} else {
  # Karşılaştırma + CSV üret
  if($ShowTable){
    .\karsilastir_4_yontem.ps1 -Seeds $ready -ShowTable -CsvPath $CsvPath | Out-Null
  } else {
    .\karsilastir_4_yontem.ps1 -Seeds $ready -CsvPath $CsvPath | Out-Null
  }
  Write-Host "CSV yazildi: $CsvPath" -ForegroundColor Cyan
}

# --- Menü (mantık korunur) ---
$teknikler = @(
  @{ id=1; name="Temel (Baseline)";         algo="temel"  },
  @{ id=2; name="Kural (Actuated)";         algo="kural"  },
  @{ id=3; name="PSO";                      algo="pso"    },
  @{ id=4; name="BayesianPSO (Optuna)";     algo="psoai"  }  # DİKKAT: run_gui/sumoGuiAcici 'psoai' bekliyor
)

function Show-Menu {
  Write-Host ""
  Write-Host "===================="
  Write-Host "TEKNIK MENUSU"
  Write-Host "===================="
  foreach($t in $teknikler){
    Write-Host ("{0}) {1}" -f $t.id, $t.name)
  }
  Write-Host "5) Seed degistir (hazir seedlerden sec)"
  Write-Host "6) Cikis"
}

# Başlangıç seed: hazır varsa ilk hazır, yoksa ilk istenen
$seed = if($ready.Count){ $ready[0] } else { $seedList[0] }

while($true){
  Write-Host ""
  Write-Host "Aktif seed: $seed" -ForegroundColor Cyan
  Show-Menu
  $choice = Read-Host "Seciminiz (1-6)"

  switch($choice){
    "1" { & .\sumoGuiAcici.ps1 -Algo "temel" -Seed $seed }
    "2" { & .\sumoGuiAcici.ps1 -Algo "kural" -Seed $seed }
    "3" { & .\sumoGuiAcici.ps1 -Algo "pso"   -Seed $seed }
    "4" { & .\sumoGuiAcici.ps1 -Algo "psoai" -Seed $seed } # BayesianPSO net'i
    "5" {
      if(-not $ready.Count){
        Write-Host "Hazir seed yok; seed degistirme icin once karsilastirma dosyalari olusmali." -ForegroundColor Yellow
        break
      }
      Write-Host "Hazir seedler: $($ready -join ',')" -ForegroundColor Green
      $newSeed = Read-Host "Secmek istedigin seed (veya Enter=iptal)"
      if($newSeed -match '^\d+$'){
        $ns = [int]$newSeed
        if($ready -contains $ns){ $seed = $ns } else { Write-Host "Bu seed hazir degil: $ns" -ForegroundColor Yellow }
      }
    }
    "6" { break }
    default { Write-Host "Gecersiz secim." -ForegroundColor Yellow }
  }
}
