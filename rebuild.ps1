# Quick rebuild script
Write-Host "Cleaning old build artifacts..." -ForegroundColor Yellow
if (Test-Path .\build) { Remove-Item -Recurse -Force .\build }
if (Test-Path .\dist)  { Remove-Item -Recurse -Force .\dist }

Write-Host "Building with PyInstaller..." -ForegroundColor Cyan
pyinstaller .\hdle_premium_installer.spec --clean --noconfirm

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nBuild successful!" -ForegroundColor Green
    Write-Host "Output: dist\HDLE_Premium\HDLE_Premium.exe" -ForegroundColor Green
    
    Write-Host "`nBuilding installer..." -ForegroundColor Cyan
    & "C:\Users\Win10_Game_OS\AppData\Local\Programs\Inno Setup 6\ISCC.exe" .\installer\installer.iss
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`nInstaller created!" -ForegroundColor Green
        Write-Host "Output: installer\output\HDLE_Premium_Setup.exe" -ForegroundColor Green
    } else {
        Write-Host "`nInstaller build failed!" -ForegroundColor Red
    }
} else {
    Write-Host "`nPyInstaller build failed!" -ForegroundColor Red
}
