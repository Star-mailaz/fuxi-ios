param(
    [ValidatePattern('^[a-f0-9]{7,40}$')][string]$DylibCommit = 'c51f5bd',
    [ValidatePattern('^[a-f0-9]{64}$')][string]$DylibSha = '9c79d2515c47874a5bfb46b06ef511114563668358aff8c9cfb1dec2eda12ed8',
    [ValidatePattern('^[a-z0-9-]+$')][string]$BackupPrefix = 'hw000torch-runtime',
    [string]$ParentSnapshot = 'D:\xiaomi13\fuxi_Backup\ios-root-hw000provider-20261116',
    [switch]$FullRestorePoint
)
$reuseBackup = $env:TORCH_REUSE_BACKUP
$ErrorActionPreference = 'Stop'
$workspace = 'D:\xiaomi13\fuxi_ios'
$gitBash = 'C:\Program Files\Git\bin\bash.exe'
Set-Location $workspace
$deadline = (Get-Date).AddMinutes(20)
Write-Output "$(Get-Date -Format HH:mm:ss) WAIT_PREVIOUS_PHONE_CHAIN"
while ((Test-Path "$workspace\work\PHONE-LOCK-000") -or
       (Test-Path "$workspace\work\hybrid-driver\HOLD-PHONE")) {
    if ((Get-Date) -gt $deadline) { throw 'Previous phone chain has not released its locks' }
    Start-Sleep -Seconds 5
}
if (Test-Path "$workspace\work\adsp-battery\hw000\HOLD") { throw 'Phone work is paused' }
$dylib = Join-Path $workspace "work\statusbar-fix\artifact-$DylibCommit\libfuxi-sb.dylib"
if ((Get-FileHash -LiteralPath $dylib -Algorithm SHA256).Hash.ToLowerInvariant() -ne $DylibSha) {
    throw 'Flashlight dylib hash differs from the CI manifest'
}
& $gitBash 'work/adsp-battery/hw000/fuxi-log.sh' pull
if ($LASTEXITCODE -ne 0) { throw 'Persistent log pull failed; staging stopped' }
$env:PYTHONUTF8 = '1'
if (-not $FullRestorePoint) {
    $runDirectory = Join-Path $workspace "work\statusbar-fix\run-$BackupPrefix-$(Get-Date -Format yyyyMMdd-HHmmss)"
    & python -X utf8 (Join-Path $workspace 'work\statusbar-fix\phone-readthrough.py') `
        --dylib $dylib --sha256 $DylibSha --output $runDirectory
    exit $LASTEXITCODE
}
$env:SKIP_CHAIN1 = '1'
$env:CLASS = 'NONE'
$env:STAGE_SCRIPT = '/d/xiaomi13/fuxi_ios/work/statusbar-fix/stage-shape.sh'
$env:SHAPE_DYLIB = "/d/xiaomi13/fuxi_ios/work/statusbar-fix/artifact-$DylibCommit/libfuxi-sb.dylib"
$env:BOOT_LOADER = 'native-dly-sb127-user-loader'
$env:BOOT_KERNEL = 'kernel-adsp-rsc-lock-5g-artifact'
$env:BOOT_VERIFIER = 'verify-loader-safety.py'
$env:OUT_PREFIX = "native-$BackupPrefix-boot"
$env:BACKUP_PREFIX = $BackupPrefix
$env:PARENT_SNAPSHOT = $ParentSnapshot
$env:NTFS_COMPRESS_BACKUP = '1'
$env:STAGE_ONLY = '1'
Remove-Item Env:REUSE_RP,Env:REUSE_STAGED -ErrorAction SilentlyContinue
if ($reuseBackup) {
    if ($DylibCommit -ne 'c51f5bd' -or $BackupPrefix -ne 'hw000torch-runtime') {
        throw 'Restore point reuse is limited to the original interrupted staging'
    }
    $expectedBackup = 'D:\xiaomi13\fuxi_Backup\ios-root-hw000torch-runtime-20261116'
    if ($reuseBackup -ne $expectedBackup) { throw 'Unexpected torch restore point' }
    foreach ($entry in @('README.txt', 'diff-blocks.txt', 'phone-blocks.txt', 'pull.bin')) {
        if (-not (Test-Path -LiteralPath (Join-Path $expectedBackup $entry))) {
            throw "Incomplete torch restore point: $entry"
        }
    }
    $env:REUSE_RP = '/d/xiaomi13/fuxi_Backup/ios-root-hw000torch-runtime-20261116'
}
& $gitBash '-c' 'exec bash work/statusbar-fix/hw000-sb-chain-provider-3edcfe8.sh 2>&1' |
    Tee-Object -FilePath "$workspace\work\statusbar-fix\$BackupPrefix-stage-$(Get-Date -Format yyyyMMdd).log"
if ($LASTEXITCODE -ne 0) { throw "Torch staging chain failed: $LASTEXITCODE" }
