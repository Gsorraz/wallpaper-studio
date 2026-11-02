param([string]$Motivo = "")
# Compilação + testes de lógica do Wallpaper Studio. SEM janelas, SEM mouse, SEM -Visivel.
# Interface NÃO é testada aqui (jogo em tela cheia): resultado fica PARCIAL.
$ErrorActionPreference = "Continue"
$raiz   = Split-Path -Parent $PSScriptRoot
$app    = Join-Path $raiz "wallpaper_studio\main.py"
$logica = Join-Path $PSScriptRoot "teste_logica.py"
$logs   = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$saida  = Join-Path $logs "ultima_saida.txt"
$jsonl  = Join-Path $logs "execucoes.jsonl"

$t0 = Get-Date
$linhas = @()
$linhas += ">>> compilacao"
& python -m py_compile $app 2>&1 | ForEach-Object { $linhas += "$_" }
$compOk = ($LASTEXITCODE -eq 0)
$linhas += "compilacao: " + $(if ($compOk) { "OK" } else { "FALHA" })

$linhas += ">>> logica"
$logicaOk = $false
if ($compOk) {
    & python -I $logica 2>&1 | ForEach-Object { $linhas += "$_" }
    $logicaOk = ($LASTEXITCODE -eq 0)
}
$linhas += ">>> interface: NAO EXECUTADA (jogo em tela cheia; rodar quando o jogo fechar)"
$linhas | Set-Content -Path $saida -Encoding UTF8

$sha = (Get-FileHash -Algorithm SHA1 -Path $app).Hash.Substring(0,10)
$tempo = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
$falhas = @($linhas | Where-Object { $_ -like "FALHA*" }).Count
$resultado = if (-not $compOk -or -not $logicaOk) { "FALHA" } else { "PARCIAL" }
$reg = [ordered]@{
    data = (Get-Date).ToString("s"); programa = "Wallpaper Studio"; versao = $sha
    motivo = $Motivo; compilacao = $compOk; logica_ok = $logicaOk
    interface = "nao_executada"; falhas = $falhas; tempo_s = $tempo; resultado = $resultado
} | ConvertTo-Json -Compress
Add-Content -Path $jsonl -Value $reg -Encoding UTF8

$linhas | Where-Object { $_ -match "^(FALHA|lógica|l.gica|compilacao|>>>)" } | ForEach-Object { Write-Output $_ }
Write-Output "RESULTADO: $resultado (versao $sha, ${tempo}s)"
if ($resultado -eq "FALHA") { exit 1 } else { exit 2 }
