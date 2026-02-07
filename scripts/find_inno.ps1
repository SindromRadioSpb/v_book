# Find Inno Setup installation
$paths = @(
    "C:\Program Files (x86)\Inno Setup 6",
    "C:\Program Files\Inno Setup 6",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6",
    "$env:PROGRAMFILES\Inno Setup 6",
    "${env:PROGRAMFILES(X86)}\Inno Setup 6"
)

foreach ($path in $paths) {
    $iscc = Join-Path $path "ISCC.exe"
    if (Test-Path $iscc) {
        Write-Host "FOUND: $iscc"
        & $iscc /?
        exit 0
    }
}

Write-Host "Inno Setup not found in standard paths"
Write-Host "Searching entire C: drive..."
Get-ChildItem C:\ -Recurse -Filter "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
