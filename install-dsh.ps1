#Requires -Version 5.1
<#
.SYNOPSIS
    把本仓库安装为 DeepSeek Harness filesystem skill，并做一次健康检查。

.DESCRIPTION
    依次执行 `scripts/dsh_manager.py install` 与 `doctor`。
    node/npm/npx 不在 PATH 时只警告、不中断——真正的结论由 doctor 给出
    （本机 DSH 自带 node 但没有 npm/npx，doctor 会把 node 降级为 warning、npm/npx 报 error）。

.EXAMPLE
    .\install-dsh.ps1
    .\install-dsh.ps1 -DshHome 'C:\tmp\dsh-home'
    .\install-dsh.ps1 -Force
#>
[CmdletBinding()]
param(
    [string]$DshHome,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
# 中文输出：Windows PowerShell 默认控制台编码可能不是 UTF-8
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"

$Repo = $PSScriptRoot
$Manager = Join-Path $Repo "scripts\dsh_manager.py"

if (-not (Test-Path -LiteralPath $Manager -PathType Leaf)) {
    throw "找不到 $Manager。请在仓库根目录运行本脚本。"
}

# python 优先；本机 `py` 不存在，但仍保留 `py -3` 回退。
$PythonExe = $null
$PythonPrefix = @()
$python = Get-Command python -ErrorAction SilentlyContinue
$py = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
    $PythonExe = $python.Source
} elseif ($py) {
    $PythonExe = $py.Source
    $PythonPrefix = @("-3")
} else {
    throw "未找到 Python。本打包工具需要 Python 3.10+（请安装 python 并加入 PATH）。"
}

Write-Host "使用 Python：$PythonExe $($PythonPrefix -join ' ')"

# 前置依赖只做提示，不中断：doctor 才是唯一的判定入口。
foreach ($Command in @("node", "npm", "npx")) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        Write-Warning "未在 PATH 中找到 $Command。安装会继续，最终结论以 doctor 输出为准。"
    }
}

$InstallArgs = @($PythonPrefix) + @($Manager)
if ($DshHome) { $InstallArgs += @("--dsh-home", $DshHome) }
$InstallArgs += "install"
if ($Force) { $InstallArgs += "--force" }

& $PythonExe @InstallArgs
if ($LASTEXITCODE -ne 0) {
    throw "install 失败（退出码 $LASTEXITCODE）。"
}

$DoctorArgs = @($PythonPrefix) + @($Manager)
if ($DshHome) { $DoctorArgs += @("--dsh-home", $DshHome) }
$DoctorArgs += "doctor"

& $PythonExe @DoctorArgs
$DoctorCode = $LASTEXITCODE

if ($DoctorCode -ne 0) {
    Write-Host ""
    Write-Host "安装完成，但 doctor 报告存在问题（退出码 $DoctorCode）。请按上面的 ERROR 逐条处理。" -ForegroundColor Yellow
}
exit $DoctorCode
