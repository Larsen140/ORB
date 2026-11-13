# Stellt die ORB.exe als Download auf GitHub bereit (Release „installer“, die Datei wird jedes Mal ersetzt).
# Braucht eine einmalige Anmeldung:  gh auth login
param([string]$Datei)
$repo = 'Larsen140/ORB'
$gh = 'C:\Program Files\GitHub CLI\gh.exe'
if (-not (Test-Path $gh)) { Write-Output 'GitHub-Werkzeug (gh) fehlt – Release übersprungen.'; exit 1 }
& $gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Output 'Nicht bei GitHub angemeldet – einmal „gh auth login“ ausführen. Release übersprungen.'; exit 1 }
& $gh release view installer -R $repo 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $gh release create installer -R $repo --title 'ORB – Installer' `
        --notes 'ORB.exe herunterladen und starten. ORB installiert sich selbst und holt sich Updates automatisch von GitHub.' 2>&1 | Out-Null
}
& $gh release upload installer $Datei --clobber -R $repo 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Output "Installer bereit: https://github.com/$repo/releases/download/installer/ORB.exe" }
else { Write-Output 'Hochladen des Installers fehlgeschlagen.'; exit 1 }
