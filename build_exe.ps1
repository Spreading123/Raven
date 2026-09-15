# Desktop Agent - Nuitka 一键构建脚本（MSVC 编译，输出原生 exe）
# 用法: powershell -ExecutionPolicy Bypass -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = "E:\miniconda3\envs\Yolo_ai_Pyside\python.exe"

Write-Host "=== 开始 Nuitka 编译 (MSVC) ===" -ForegroundColor Cyan

& $python -m nuitka `
    --standalone `
    --msvc=latest `
    --assume-yes-for-downloads `
    --enable-plugin=pyside6 `
    --include-data-dir=ui=ui `
    --include-data-files=.env=.env `
    --windows-console-mode=disable `
    --output-dir=dist `
    --remove-output `
    main.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "=== 编译失败 ===" -ForegroundColor Red
    exit $LASTEXITCODE
}

$dist = Join-Path $PSScriptRoot "dist\main.dist"
Write-Host "=== 构建完成: $dist ===" -ForegroundColor Green
Write-Host "exe: $dist\main.exe" -ForegroundColor Green
