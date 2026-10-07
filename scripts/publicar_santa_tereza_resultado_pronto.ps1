$ErrorActionPreference = "Stop"

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') falhou com codigo $LASTEXITCODE"
    }
}

function Assert-ProductOnlyStaged {
    param([string[]]$Allowed, [string]$Phase)
    # Inspect both sides of a rename; do not remove or hide foreign entries.
    $staged = @(& git -c core.quotepath=false diff --cached --name-only --no-renames)
    if ($LASTEXITCODE -ne 0) {
        throw "Nao foi possivel verificar o indice antes de $Phase. Publicacao bloqueada."
    }
    $foreign = @($staged | Where-Object { $_ -and $Allowed -notcontains $_.Replace("\", "/") })
    if ($foreign.Count -gt 0) {
        throw "Indice contem staged alheio antes de ${Phase}: $($foreign -join ', '). Nenhuma entrada foi removida; publicacao bloqueada."
    }
}

$repoRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
if (-not $repoRoot) { throw "Execute este script dentro do repositorio PREVINE." }
Set-Location $repoRoot

$trackedOutputs = @(
    "santa_tereza_previsao_inundacao.html",
    "santa_tereza_inundacao.html",
    "santa_tereza_painel_evacuacao.html",
    "pesquisas/santa-tereza-painel-evacuacao.html",
    "pesquisas/santa-tereza-mapa-impacto.html",
    "pesquisas/santa-tereza-mapa-margem.html",
    "pesquisas/santa-tereza-rota-fuga-ruas.html",
    "santa_tereza_rota_fuga_ruas_cenario.html",
    "pesquisas/santa-tereza-rota-fuga-ruas-cenario.html",
    "assets/data/santa_tereza_inundacao/contornos_mancha.json",
    "assets/data/santa_tereza_inundacao/contornos_extravasamento.json",
    "assets/data/santa_tereza_inundacao/hand_lidar_5m_diagnostic.json",
    "assets/data/santa_tereza_inundacao/painel_evacuacao_hand_campo_diagnostic.json"
)
$newOutputs = @(
    "assets/data/santa_tereza_inundacao/mdt/altitude_terreno_lidar_10m.json",
    "assets/data/santa_tereza_inundacao/mdt/altitude_terreno_lidar_10m.png",
    "assets/data/santa_tereza_inundacao/mdt/mdt_santa_tereza_lidar_10m_visual.png"
)
$allowed = @($trackedOutputs + $newOutputs) | ForEach-Object { $_.Replace("\","/") }
Assert-ProductOnlyStaged -Allowed $allowed -Phase "sincronizacao/recalculo"

# Alteracoes locais de outros projetos sao preservadas e NAO entram no commit.
# O commit abaixo usa git add apenas nos arquivos de Santa Tereza.
$dirty = @(& git status --porcelain=v1)
$unrelated = @()
foreach ($line in $dirty) {
    if (-not $line) { continue }
    $p = $line.Substring(3).Trim().Replace("\","/")
    if ($p -like "* -> *") { $p = ($p -split " -> ")[-1] }
    if ($allowed -notcontains $p) { $unrelated += $p }
}
if ($unrelated.Count -gt 0) {
    Write-Host ("Aviso: preservando alteracoes locais de outros projetos (nao serao commitadas): {0}" -f ($unrelated -join ", ")) -ForegroundColor Yellow
}

Write-Host "1/5 Sincronizando e validando o resultado ja gerado..." -ForegroundColor Cyan
& python "codigo_python/01_previsao_ao_vivo/atualizar_hand_previsao_santa_tereza.py"
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao sincronizar o HAND LiDAR da pagina ao vivo com a pagina historica."
}
& python "scripts/recalcular_painel_evacuacao_hand_campo.py"
if ($LASTEXITCODE -ne 0) {
    throw "Contrato/recálculo dos consumidores de campo falhou. Nada sera publicado."
}
$diagPath = "assets/data/santa_tereza_inundacao/hand_lidar_5m_diagnostic.json"
if (-not (Test-Path $diagPath)) { throw "Diagnostico ausente: $diagPath" }
$d = Get-Content $diagPath -Raw | ConvertFrom-Json

if ($d.d8_scheme -ne "esri") { throw "D8 inesperado: $($d.d8_scheme)." }
if ([double]$d.receiver_fraction_assigned -lt 0.95) {
    throw ("Receptores insuficientes: {0:P2}." -f [double]$d.receiver_fraction_assigned)
}
if ([double]$d.drained_fraction -lt 0.90) {
    throw ("Drenagem insuficiente: {0:P2}." -f [double]$d.drained_fraction)
}
if ($d.terrain_modified_by_water_filter -ne $false) {
    throw "O filtro de agua alterou o MDT. Publicacao bloqueada."
}
if (([string]$d.water_connectivity_filter -notmatch "main-river") -or ([string]$d.water_connectivity_filter -notmatch "raw LiDAR")) {
    throw "Filtro de conectividade da agua nao confirmou D8/barreira no LiDAR bruto ate o rio principal."
}
if ([int]$d.contornos_features -lt 251) {
    throw "Contornos insuficientes: $($d.contornos_features). Regere o HAND ate 25 m antes de publicar."
}
if ([double]$d.contour_max_m -lt 25.0) {
    throw "HAND maximo de contorno insuficiente: $($d.contour_max_m) m."
}
if ($d.spatialization_rule -ne "nivel_regua_m - 1.60 m") {
    throw "Regra de espacializacao inesperada: $($d.spatialization_rule)."
}
foreach ($p in $newOutputs) {
    if (-not (Test-Path $p)) { throw "Saida ausente: $p" }
}
$page = Get-Content "santa_tereza_previsao_inundacao.html" -Raw
if ($page -notmatch "altitude_terreno_lidar_10m\.json") {
    throw "A pagina nao usa o MDT LiDAR same-source."
}
if ($page -match "altitude_terreno_10m_refinado\.json|mdt_santa_tereza_10m_refinado_visual\.png") {
    throw "Referencia ao MDT legado detectada."
}
if ($page -notmatch "if\(value===255\) return null" -or $page -notmatch "saturated:value===Number\(HAND.saturated_value\)") {
    throw "Contrato NoData 255 ausente."
}
if ($page -notmatch "CONTORNOS_URL='assets/data/santa_tereza_inundacao/contornos_extravasamento\.json'") {
    throw "A pagina ao vivo nao usa o contorno de extravasamento derivado do HAND LiDAR."
}
if ($page -notmatch "stageToSpatialHand\(cm,zeroCm=HAND_ZERO_DEFAULT_CM\)") {
    throw "A pagina nao confirmou a espacializacao pelo zero de 1,60 m."
}
Write-Host ("   D8={0}; receptores={1:P2}; drena_ao_rio={2:P2}; contornos={3}" -f $d.d8_scheme,[double]$d.receiver_fraction_assigned,[double]$d.drained_fraction,[int]$d.contornos_features) -ForegroundColor Green

Write-Host "2/5 Incorporando atualizacoes independentes da main..." -ForegroundColor Cyan
Assert-ProductOnlyStaged -Allowed $allowed -Phase "fetch"
Invoke-Git fetch origin
$localHead = (& git rev-parse HEAD).Trim()
$remoteHead = (& git rev-parse origin/main).Trim()
if ($localHead -ne $remoteHead) {
    $remoteChanged = @(& git diff --name-only "$localHead..$remoteHead") | ForEach-Object { $_.Trim().Replace("\","/") } | Where-Object { $_ }
    $overlap = @($remoteChanged | Where-Object { $allowed -contains $_ })
    if ($overlap.Count -gt 0) {
        throw "A main mudou em arquivos do proprio produto: $($overlap -join ', '). Nao vou sobrescrever."
    }
    Write-Host ("   Main avancou apenas em arquivos independentes: {0}" -f ($remoteChanged -join ", ")) -ForegroundColor Yellow
    Invoke-Git merge --ff-only origin/main
}

# Revalida que as saidas locais sobreviveram ao fast-forward.
foreach ($p in $newOutputs) {
    if (-not (Test-Path $p)) { throw "Saida desapareceu apos atualizar a main: $p" }
}

Write-Host "3/5 Criando commit do produto validado..." -ForegroundColor Cyan
Assert-ProductOnlyStaged -Allowed $allowed -Phase "git add"
foreach ($p in $trackedOutputs) {
    & git add -- $p
    if ($LASTEXITCODE -ne 0) { throw "git add falhou para: $p" }
}
foreach ($p in $newOutputs) {
    & git add -- $p
    if ($LASTEXITCODE -ne 0) { throw "git add falhou para: $p" }
}
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { throw "Nenhuma alteracao para publicar." }
if ($LASTEXITCODE -ne 1) { throw "Falha ao verificar diferencas staged. Publicacao bloqueada." }
Assert-ProductOnlyStaged -Allowed $allowed -Phase "commit"
Invoke-Git commit -m "publish(st): MDT LiDAR, HAND e agua conectada"

Write-Host "4/5 Sincronizando com robos que possam ter atualizado a main..." -ForegroundColor Cyan
$published = $false
for ($attempt = 1; $attempt -le 5; $attempt++) {
    Assert-ProductOnlyStaged -Allowed $allowed -Phase "fetch de publicacao"
    Invoke-Git fetch origin
    $remote = (& git rev-parse origin/main).Trim()
    $head = (& git rev-parse HEAD).Trim()

    & git merge-base --is-ancestor $remote $head
    $remoteAlreadyIncluded = ($LASTEXITCODE -eq 0)

    if (-not $remoteAlreadyIncluded) {
        Write-Host "   A main avancou de novo; reaplicando o commit sobre a versao atual (tentativa $attempt/5)..." -ForegroundColor Yellow
        & git rebase --autostash origin/main
        if ($LASTEXITCODE -ne 0) {
            & git rebase --abort 2>$null
            throw "Conflito real com a main. Publicacao abortada sem force push."
        }
    }

    Write-Host "5/5 Enviando para a main (tentativa $attempt/5)..." -ForegroundColor Cyan
    & git push origin HEAD:main
    if ($LASTEXITCODE -eq 0) {
        $published = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $published) {
    throw "A main mudou repetidamente e o push nao estabilizou apos 5 tentativas. Nada foi forcado."
}

Write-Host ""
Write-Host "PUBLICADO COM SUCESSO." -ForegroundColor Green
Write-Host ("D8={0}; receptores={1:P2}; drena_ao_rio={2:P2}; contornos={3}" -f $d.d8_scheme,[double]$d.receiver_fraction_assigned,[double]$d.drained_fraction,[int]$d.contornos_features)
Write-Host "MDT LiDAR preservado; filtro aplicado somente na agua."
Write-Host "URL: https://previne-taquari-antas.github.io/Previne-Taquari-Antas---Redes-Neurais/santa_tereza_previsao_inundacao.html"
