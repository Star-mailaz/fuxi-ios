param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')][string]$Name = '',
    [string]$Harness = '',
    [string]$Distro = 'Ubuntu-26.04'
)
$ErrorActionPreference = 'Stop'
$env:WSL_UTF8 = '1'

function ConvertTo-WslPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -notmatch '^[A-Za-z]:\\') { throw 'An absolute drive path is required' }
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

$buildScript = ConvertTo-WslPath (Join-Path $PSScriptRoot 'fuxi-sb-build.sh')
$verifier = ConvertTo-WslPath (Join-Path $PSScriptRoot 'verify-sb-shape.py')
$revision = & git -C $Harness rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify harness revision' }
$dirty = @(& git -C $Harness status --porcelain).Count
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect harness working tree' }
$arguments = @('--harness', (ConvertTo-WslPath $Harness), '--verifier', $verifier,
    '--note', "harness $revision dirty=$dirty")
if ($Name) { $arguments += @('--name', $Name) }
$quoted = ($arguments | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join ' '
$quotedScript = "'" + ($buildScript -replace "'", "'\''") + "'"
$launch = 'build_script=$(mktemp /root/fuxi-sb-build-XXXXXX.sh) || exit 1; trap ''rm -f $build_script'' EXIT; tr -d ''\r'' < ' + $quotedScript + ' > $build_script && bash $build_script ' + $quoted
$ErrorActionPreference = 'Continue'
& wsl.exe -d $Distro -u root --exec bash -c $launch
exit $LASTEXITCODE
