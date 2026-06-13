param(
  [Parameter(Mandatory = $true)]
  [string]$RemoteModelUrl,

  [string]$RemoteModel = "qwen3:1.7b",

  [string]$RemoteModelApiKey = "",

  [switch]$EnableRagLlm,

  [switch]$EnableOcr
)

$ErrorActionPreference = "Stop"

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $scriptPath "..")
$apiDir = Join-Path $root "apps/api"
$desktopDir = Join-Path $root "apps/desktop"
$desktopBuildDir = Join-Path $desktopDir "build"
$apiDistDir = Join-Path $apiDir "dist/adala-api"
$apiBuildDir = Join-Path $apiDir "build"
$releaseDir = Join-Path $desktopDir "release"

function Write-Step($message) {
  Write-Host ""
  Write-Host "==> $message" -ForegroundColor Cyan
}

function Remove-GeneratedDirectory($path) {
  if (-not (Test-Path $path)) {
    return
  }
  $resolved = Resolve-Path $path
  if (-not ($resolved.Path.StartsWith($root.Path))) {
    throw "Refusing to remove path outside repository: $resolved"
  }
  Remove-Item -LiteralPath $resolved.Path -Recurse -Force
}

Write-Step "Preparing desktop default settings"
New-Item -ItemType Directory -Force $desktopBuildDir | Out-Null
$settings = [ordered]@{
  ollamaBaseUrl = $RemoteModelUrl.TrimEnd("/")
  ollamaModel = $RemoteModel
  ollamaApiKey = $RemoteModelApiKey
  ragLlmEnabled = [bool]$EnableRagLlm
  ocrEnabled = [bool]$EnableOcr
}
$settings | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $desktopBuildDir "settings.default.json")

Write-Step "Installing Node dependencies"
Push-Location $root
npm install
Pop-Location

Push-Location $desktopDir
npm install
Pop-Location

Write-Step "Preparing compact Python backend"
Push-Location $apiDir
if (-not (Test-Path ".venv")) {
  py -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r requirements-desktop.txt
Remove-GeneratedDirectory $apiDistDir
Remove-GeneratedDirectory $apiBuildDir
& ".\.venv\Scripts\pyinstaller.exe" `
  --noconfirm `
  --clean `
  --name adala-api `
  --onedir `
  --hidden-import app.main `
  --collect-submodules app `
  launcher.py
Pop-Location

Write-Step "Building Next.js UI"
Push-Location $root
npm run build:web
Pop-Location

Write-Step "Building Windows installer"
Remove-GeneratedDirectory $releaseDir
Push-Location $root
npm run build:desktop
Pop-Location

Write-Step "Installer build complete"
Write-Host "Output folder: $releaseDir" -ForegroundColor Green
Get-ChildItem -Path $releaseDir -Filter "*.exe" -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "Installer: $($_.FullName)" -ForegroundColor Green
}
