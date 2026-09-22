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
if ([int]$d.contornos_features -lt 251) {
    throw "Contornos insuficientes: $($d.contornos_features). Esperado: pelo menos 251 (0 a 25 m em passos de 0,1 m)."
}
if ([double]$d.contour_max_m -lt 25.0) {
    throw "HAND maximo de contorno insuficiente: $($d.contour_max_m) m."
}
if ($d.spatialization_rule -ne "nivel_regua_m - 1.60 m") {
    throw "Regra de espacializacao inesperada: $($d.spatialization_rule)."
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
if ($page -notmatch "contornos_mancha\.json") {
    throw "A pagina nao esta usando a mancha total HAND."
}
if ($page -notmatch "stageToSpatialHand\(cm,zeroCm=HAND_ZERO_DEFAULT_CM\)") {
    throw "A pagina nao confirmou a espacializacao pelo zero de 1,60 m."
}

Write-Host ("   D8={0}; receptores={1:P2}; drena_ao_rio={2:P2}; contornos={3}" -f $d.d8_scheme,[double]$d.receiver_fraction_assigned,[double]$d.drained_fraction,[int]$d.contornos_features) -ForegroundColor Green

Write-Host "4/6 Conferindo atualizacoes da main durante o processamento..." -ForegroundColor Cyan
Invoke-Git fetch origin
$latest = (& git rev-parse origin/main).Trim()
if ($latest -ne $base) {
    $remoteChanged = @(& git diff --name-only "$base..$latest") | ForEach-Object { $_.Trim().Replace("\\","/") } | Where-Object { $_ }
    $overlap = @($remoteChanged | Where-Object { $allowed -contains $_ })
    if ($overlap.Count -gt 0) {
        throw "A main mudou em arquivos do proprio produto durante o processamento: $($overlap -join ', '). Rode novamente para evitar sobrescrever mudancas reais."
    }
    Write-Host ("   A main avancou apenas em arquivos independentes: {0}" -f ($remoteChanged -join ", ")) -ForegroundColor Yellow
    Invoke-Git merge --ff-only origin/main
}

Write-Host "5/6 Criando commit somente com o produto de Santa Tereza..." -ForegroundColor Cyan
foreach ($p in $trackedOutputs) {
    & git add -- $p
    if ($LASTEXITCODE -ne 0) { throw "git add falhou para: $p" }
}
foreach ($p in $newOutputs) {
    & git add -- $p
    if ($LASTEXITCODE -ne 0) { throw "git add falhou para: $p" }
}
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    throw "Nenhuma alteracao foi gerada."
}
Invoke-Git commit -m "publish(st): atualiza MDT LiDAR, HAND e agua conectada"

Write-Host "6/6 Publicando na main..." -ForegroundColor Cyan
$published = $false
for ($attempt = 1; $attempt -le 5; $attempt++) {
    Invoke-Git fetch origin
    $remote = (& git rev-parse origin/main).Trim()
    $head = (& git rev-parse HEAD).Trim()
    & git merge-base --is-ancestor $remote $head
    $remoteAlreadyIncluded = ($LASTEXITCODE -eq 0)
    if (-not $remoteAlreadyIncluded) {
        Write-Host "   A main avancou novamente; reaplicando o commit sobre a versao atual (tentativa $attempt/5)..." -ForegroundColor Yellow
        & git rebase origin/main
        if ($LASTEXITCODE -ne 0) {
            & git rebase --abort 2>$null
            throw "Conflito real com a main. Publicacao abortada sem force push."
        }
    }
    & git push origin HEAD:main
    if ($LASTEXITCODE -eq 0) { $published = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $published) {
    throw "A main mudou repetidamente e o push nao estabilizou apos 5 tentativas. Nada foi forcado."
}

Write-Host ""
Write-Host "PUBLICADO COM SUCESSO." -ForegroundColor Green
Write-Host "Santa Tereza: MDT LiDAR preservado; HAND e agua regenerados; pagina enviada para a main."
Write-Host "URL: https://julianacarolinoreis.github.io/Previne-Taquari-Antas---Redes-Neurais/santa_tereza_previsao_inundacao.html"
