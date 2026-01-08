# sumo-caglayanBridge-signal-optimization

This repository contains traffic signal control/optimization experiments for the Caglayan Bridge scenario in SUMO.

Compared methods:
- Baseline
- Rule-based control
- PSO (Particle Swarm Optimization)
- Bayesian optimization (Optuna)

## Project Structure
- `aktif/` : Active scenario files (sumocfg, net, rou, add, detectors)
- Root `.py` files: Algorithms and metrics/helper code
- Root `.ps1` files: Windows PowerShell scripts to run and compare methods

## How to Run (Windows)
1) Make sure SUMO is installed (sumo / sumo-gui should work).
2) Open PowerShell in the project folder.
3) Run one of the scripts:

- `.\teknikler.ps1` (PowerShell in the project folder)
- `.\run_gui.ps1` (run with GUI)
- `.\sumoGuiAcici.ps1` (open SUMO GUI)
- `.\karsilastir_4_yontem.ps1` (compare 4 methods)
- `.\karsilastir_seed.ps1` (seed-based comparison)

Note: You may need small edits depending on your local SUMO path/settings.

## Notes
- Large output folders and report files may not be included in this repository.
---

# Turkish
...
# sumo-caglayanBridge-signal-optimization

Bu repo, SUMO üzerinde Çağlayan Köprüsü senaryosu için trafik ışığı kontrolünü/optimizasyonunu içerir.

Karşılaştırılan yöntemler:
- Temel (baseline)
- Kural tabanlı kontrol
- PSO (Particle Swarm Optimization)
- Bayesian optimizasyon (Optuna)

## Klasör Yapısı
- `aktif/` : Çalıştırılan ana senaryo dosyaları (sumocfg, net, rou, add, dedektörler)
- Kökteki `.py` dosyaları: Algoritmalar ve ölçüm/yardımcı kodlar
- Kökteki `.ps1` dosyaları: Windows PowerShell ile çalıştırma ve karşılaştırma scriptleri

## Çalıştırma (Windows)
1) SUMO’nun kurulu olduğundan emin ol (sumo / sumo-gui çalışmalı).
2) Proje klasöründe PowerShell aç.
3) Aşağıdaki scriptlerden birini çalıştır:
- `.\teknikler.ps1` (Proje Klasöründe PowerShell ile)
- `.\run_gui.ps1` (GUI ile çalıştırma)
- `.\sumoGuiAcici.ps1` (SUMO GUI açıcı)
- `.\karsilastir_4_yontem.ps1` (4 yöntemi karşılaştırma)
- `.\karsilastir_seed.ps1` (seed bazlı karşılaştırma)

Not: Scriptler SUMO yolu/ayarları için sistemine göre küçük düzenleme isteyebilir.

## Notlar
- Büyük çıktı klasörleri ve rapor dosyaları bu repoya eklenmemiş olabilir.
