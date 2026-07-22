$ErrorActionPreference = "Continue"

$repo = "D:\PREVINE\repo_site"
$logDir = "D:\PREVINE\logs"
$lockPath = Join-Path $logDir "robo_ao_vivo_mucum_local.lock"
$logPath = Join-Path $logDir ("robo_ao_vivo_mucum_local_{0}.log" -f (Get-Date -Format "yyyyMMdd"))

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

function Invoke-LoggedCommand {
    param(
        [string]$Label,
        [string]$Command,
        [bool]$FailOnError = $true
    )
    Write-Log ("Executando: " + $Label)
    $stamp = "{0}_{1}" -f ([guid]::NewGuid().ToString("N")), (Get-Date -Format "HHmmss")
    $stdoutPath = Join-Path $env:TEMP ("previne_stdout_" + $stamp + ".log")
    $stderrPath = Join-Path $env:TEMP ("previne_stderr_" + $stamp + ".log")
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", $Command) -WorkingDirectory (Get-Location).Path -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    foreach ($path in @($stdoutPath, $stderrPath)) {
        if (Test-Path $path) {
            Get-Content $path | ForEach-Object {
                if ($_ -ne "") { Write-Log $_ }
            }
            Remove-Item -Force $path -ErrorAction SilentlyContinue
        }
    }
    $code = $proc.ExitCode
    if ($FailOnError -and $code -ne 0) {
        throw ("Comando falhou ({0}) com codigo {1}" -f $Label, $code)
    }
    return $code
}

$lockStream = $null
try {
    $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
    Write-Log "Outro ciclo de Mucum ainda esta rodando; encerrando este disparo."
    exit 0
}

try {
    Set-Location $repo
    Write-Log "Inicio do ciclo local de Mucum."

    Invoke-LoggedCommand "git pull inicial" "git pull --rebase --autostash origin main" | Out-Null
    Invoke-LoggedCommand "gerar Mucum" "python codigo_python\01_previsao_ao_vivo\gerar_previsao_ao_vivo_mucum.py" | Out-Null

    Invoke-LoggedCommand "git add Mucum" "git add previsao_ao_vivo_mucum.json" | Out-Null
    $diffCode = Invoke-LoggedCommand "git diff staged quiet" "git diff --staged --quiet" $false
    if ($diffCode -eq 0) {
        Write-Log "Sem mudanca de Mucum para publicar."
    } else {
        Invoke-LoggedCommand "git commit Mucum" "git commit -m ""bot-local: atualiza Mucum ao vivo [skip ci]""" | Out-Null

        $publicado = $false
        for ($tentativa = 1; $tentativa -le 5; $tentativa++) {
            Invoke-LoggedCommand ("git pull antes do push tentativa " + $tentativa) "git pull --rebase --autostash origin main" | Out-Null
            $pushCode = Invoke-LoggedCommand ("git push tentativa " + $tentativa) "git push origin main" $false
            if ($pushCode -eq 0) {
                $publicado = $true
                break
            }
            Write-Log ("Push de Mucum falhou na tentativa {0}; tentando novamente." -f $tentativa)
            Start-Sleep -Seconds 5
        }

        if (-not $publicado) {
            throw "Nao foi possivel publicar Mucum depois de 5 tentativas."
        }
    }

    Write-Log "Fim do ciclo local de Mucum com sucesso."
} catch {
    Write-Log ("ERRO: " + $_.Exception.Message)
    exit 1
} finally {
    if ($lockStream) {
        $lockStream.Close()
        $lockStream.Dispose()
    }
}
