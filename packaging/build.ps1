# 一键打包脚本：在项目根目录跑，会激活 .venv 并调用 PyInstaller。
# 产物在 dist\TemuDelisting\ 下，把这整个文件夹压缩成 zip 发给同事即可。

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

& "$ProjectRoot\.venv\Scripts\Activate.ps1"

Write-Host "[build] 清理旧的打包产物..."
Remove-Item -Recurse -Force "$ProjectRoot\dist\TemuDelisting" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$ProjectRoot\build" -ErrorAction SilentlyContinue

Write-Host "[build] 开始打包（第一次会比较慢，要打包 PySide6 + Playwright driver）..."
pyinstaller packaging\temu_delisting_gui.spec --distpath dist --workpath build --noconfirm

Write-Host "[build] 完成。产物在: $ProjectRoot\dist\TemuDelisting\"
Write-Host "[build] 把整个 TemuDelisting 文件夹压缩成 zip 发给同事即可。"
