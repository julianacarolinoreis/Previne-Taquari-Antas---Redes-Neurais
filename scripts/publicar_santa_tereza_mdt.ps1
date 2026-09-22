$ErrorActionPreference = "Stop"

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') falhou com codigo $LASTEXITCODE"
    }
}

$repoRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
if (-not $repoRoot) {
    throw "Execute este script dentro do repositorio PREVINE."
}
Set-Location $repoRoot

$sourceDir = "D:\PREVINE\hand\santa tereza"
$requiredRasters = @(
    "FILL_CLIP_MOSAICO_LIDAR_RS.tif",
    "FLOWACC_CLIP_MOSAICO_LIDAR_RS.tif",
    "FLOWDIR_CLIP_MOSAICO_LIDAR_RS.tif"
)
foreach ($name in $requiredRasters) {
    $p = Join-Path $sourceDir $name
    if (-not (Test-Path $p)) {
        throw "Raster obrigatorio ausente: $p"
    }
}

$trackedOutputs = @(
    "santa_tereza_previsao_inundacao.html",
    "assets/data/santa_tereza_inundacao/contornos_mancha.json",
    "assets/data/santa_tereza_inundacao/contornos_extravasamento.json",
    "assets/data/santa_tereza_inundacao/hand_lidar_5m_diagnostic.json"
)
$newOutputs = @(
    "assets/data/santa_tereza_inundacao/mdt/altitude_terreno_lidar_10m.json",
    "assets/data/santa_tereza_inundacao/mdt/altitude_terreno_lidar_10m.png",
    "assets/data/santa_tereza_inundacao/mdt/mdt_santa_tereza_lidar_10m_visual.png"
)
$allowed = @($trackedOutputs + $newOutputs) | ForEach-Object { $_.Replace("\","/") }

# Nao mistura a publicacao com outros trabalhos locais.
$dirty = @(& git status --porcelain=v1)
foreach ($line in $dirty) {
    if (-not $line) { continue }
    $p = $line.Substring(3).Trim().Replace("\","/")
    if ($p -like "* -> *") { $p = ($p -split " -> ")[-1] }
    if ($allowed -notcontains $p) {
        throw "Ha alteracao local fora do pacote de Santa Tereza: $p. Publicacao abortada para nao misturar trabalhos."
    }
}

Write-Host "1/6 Atualizando a base..." -ForegroundColor Cyan
foreach ($p in $trackedOutputs) {
    & git restore --worktree -- $p 2>$null
}
foreach ($p in $newOutputs) {
    if (Test-Path $p) { Remove-Item -Force $p }
}
Invoke-Git fetch origin
Invoke-Git merge --ff-only origin/main
$base = (& git rev-parse HEAD).Trim()

Write-Host "2/6 Regenerando HAND + MDT LiDAR + agua conectada..." -ForegroundColor Cyan
& python "codigo_python/02_mdt_hand_mancha/gerar_hand_lidar_santa_tereza.py"
if ($LASTEXITCODE -ne 0) {
    throw "Gerador de Santa Tereza falhou. Nada sera publicado."
}

Write-Host "3/6 Validando diagnostico..." -ForegroundColor Cyan
$diagPath = "assets/data/santa_tereza_inundacao/hand_lidar_5m_diagnostic.json"
$d = Get-Content $diagPath -Raw | ConvertFrom-Json

if ($d.d8_scheme -ne "esri") {
    throw "D8 inesperado: $($d.d8_scheme). Esperado: esri."
}
if ([double]$d.receiver_fraction_assigned -lt 0.95) {
    throw ("Somente {0:P2} das celulas receberam receptor. Publicacao bloqueada." -f [double]$d.receiver_fraction_assigned)
}
if ([double]$d.drained_fraction -lt 0.90) {
    throw ("Somente {0:P2} do terreno drenou ao rio principal. Publicacao bloqueada." -f [double]$d.drained_fraction)
}
if ($d.terrain_modified_by_water_filter -ne $false) {
    throw "O filtro de agua alterou o terreno. Publicacao bloqueada."
}
if ($d.water_connectivity_filter -notmatch "connected-to-main-river") {
    throw "Filtro de conectividade da agua nao confirmado."
}
if ([int]$d.contornos_features -lt 100) {
    throw "Poucos contornos gerados: $($d.contornos_features)."
}

foreach ($p in $newOutputs) {
    if (-not (Test-Path $p)) { throw "Saida esperada ausente: $p" }
}
$page = Get-Content "santa_tereza_previsao_inundacao.html" -Raw
if ($page -notmatch "altitude_terreno_lidar_10m\.json") {
    throw "A pagina nao ativou o MDT LiDAR same-source."
}
if ($page -match "altitude_terreno_10m_refinado\.json|mdt_santa_tereza_10m_refinado_visual\.png") {
    throw "A pagina voltou a referenciar o MDT legado. Publicacao bloqueada."
}
if ($page -notmatch "value===255\?null:value") {
    throw "Contrato NoData 255 nao encontrado na pagina."
}

Write-Host ("   D8={0}; receptores={1:P2}; drena_ao_rio={2:P2}; contornos={3}" -f $d.d8_scheme,[double]$d.receiver_fraction_assigned,[double]$d.drained_fraction,[int]$d.contornos_features) -ForegroundColor Green

Write-Host "4/6 Conferindo se a main nao mudou durante o processamento..." -ForegroundColor Cyan
Invoke-Git fetch origin
$latest = (& git rev-parse origin/main).Trim()
if ($latest -ne $base) {
    throw "A origin/main mudou enquanto o raster era processado. Rode o mesmo comando novamente para regenerar sobre a versao mais nova."
}

Write-Host "5/6 Criando commit somente com o produto de Santa Tereza..." -ForegroundColor Cyan
Invoke-Git add -- $trackedOutputs
Invoke-Git add -- $newOutputs
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    throw "Nenhuma alteracao foi gerada."
}
Invoke-Git commit -m "publish(st): atualiza MDT LiDAR, HAND e agua conectada"

Write-Host "6/6 Publicando na main..." -ForegroundColor Cyan
& git push origin HEAD:main
if ($LASTEXITCODE -ne 0) {
    throw "O push foi recusado (provavelmente a main avancou). Rode este mesmo script novamente; nao use force push."
}

Write-Host ""
Write-Host "PUBLICADO COM SUCESSO." -ForegroundColor Green
Write-Host "Santa Tereza: MDT LiDAR preservado; HAND e agua regenerados; pagina enviada para a main."
Write-Host "URL: https://julianacarolinoreis.github.io/Previne-Taquari-Antas---Redes-Neurais/santa_tereza_previsao_inundacao.html"
