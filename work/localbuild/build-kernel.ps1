# 從 Windows 啟動 WSL 內的本機核心建置。流程說明在工作區根目錄 AGENTS.md 第 9 節。
# 例：.\build-kernel.ps1 -Ram 9g -Name w19-try1
param(
    [ValidateSet('full', '9g')][string]$Ram = 'full',
    [string]$Name = '',
    [string]$Harness = '',
    [string]$Ath12k = '',
    [switch]$Clean,
    [switch]$Tests,
    [int]$Jobs = 0,
    [string]$Distro = 'Ubuntu-26.04'
)
$ErrorActionPreference = 'Stop'
$env:WSL_UTF8 = '1'

function ConvertTo-WslPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    '/mnt/' + $full.Substring(0, 1).ToLower() + ($full.Substring(2) -replace '\\', '/')
}

if (-not $Harness) {
    # 工作區用 work\adsp-battery\harness；從 fuxi-ios 倉庫執行時，倉庫根目錄就是 harness
    $Harness = Join-Path $PSScriptRoot '..\adsp-battery\harness'
    if (-not (Test-Path -LiteralPath (Join-Path $Harness '.github\workflows\kernel-adsp-battery.yml'))) {
        $Harness = Join-Path $PSScriptRoot '..\..'
    }
    $Harness = [IO.Path]::GetFullPath($Harness)
}

$script = ConvertTo-WslPath (Join-Path $PSScriptRoot 'fuxi-kernel-build.sh')
$arguments = @('--ram', $Ram, '--harness', (ConvertTo-WslPath $Harness))
if ($Name) { $arguments += @('--name', $Name) }
if ($Ath12k) { $arguments += @('--ath12k', (ConvertTo-WslPath $Ath12k)) }
if ($Clean) { $arguments += '--clean' }
if ($Tests) { $arguments += '--tests' }
if ($Jobs -gt 0) { $arguments += @('--jobs', "$Jobs") }
# harness 是 Windows 路徑的 git worktree，WSL 內的 git 讀不到，所以在這裡取版本資訊
$rev = (& git -C $Harness rev-parse HEAD 2>$null)
$dirty = @(& git -C $Harness status --porcelain 2>$null).Count
$arguments += @('--note', "harness $rev dirty=$dirty")

# 腳本存在 Windows 磁碟上，先去掉可能的 CR 再執行。參數用單引號包好接進同一個字串，
# 避免 Windows PowerShell 5.1 傳遞內嵌雙引號給 wsl.exe 時被吃掉。
$quoted = ($arguments | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join ' '
# 每次用獨立副本，第二個啟動器才不會在鎖檔檢查前覆寫正在讀取的腳本。
$quotedScript = "'" + ($script -replace "'", "'\''") + "'"
$launch = 'build_script=$(mktemp /root/fuxi-kernel-build-XXXXXX.sh) || exit 1; trap ''rm -f $build_script'' EXIT; tr -d ''\r'' < ' + $quotedScript + ' > $build_script && bash $build_script ' + $quoted
# wsl.exe 常把「Failed to mount T:\」這類無害警告寫到 stderr。Stop 模式下只要呼叫端轉向了 stderr
# （*>、2>&1、或由代理工具在前景執行），PowerShell 5.1 就把它當成致命錯誤，建置根本沒開始。
# 成敗只看 wsl 的結束碼。
$ErrorActionPreference = 'Continue'
& wsl.exe -d $Distro -u root --exec bash -c $launch
exit $LASTEXITCODE
