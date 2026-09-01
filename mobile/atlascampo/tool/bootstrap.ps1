param(
  [string]$ProjectPath = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
  throw 'Flutter não está instalado ou não está no PATH.'
}

Push-Location $ProjectPath
try {
  if (-not (Test-Path 'android') -or -not (Test-Path 'ios')) {
    flutter create --platforms=android,ios .
  }
  flutter pub get
  flutter analyze
  flutter test
} finally {
  Pop-Location
}
