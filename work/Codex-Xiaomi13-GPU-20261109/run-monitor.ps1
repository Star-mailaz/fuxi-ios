param([string]$Loader, [string]$Out, [string]$Log, [int]$Seconds = 240, [int]$Reset = 4, [string]$Kernel = 'kernel-surfrow2-artifact', [switch]$TourShots, [switch]$Framebuffer, [int]$MonitorIdle = -1, [int]$FramebufferHeight = 2400)
$e = 'D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109'
$env:PATH = 'D:\xiaomi13\fuxi_ios;' + $env:PATH
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
Set-Location 'D:\xiaomi13\fuxi_ios'
& python 'D:\xiaomi13\fuxi_ios\ios-fuxi\tools\fuxi-xnu-monitor.py' --kernel "$e\$Kernel\kernel.development.fuxi.unstripped" --payload "$e\$Loader\payload.bin" --out "$e\$Out" --seconds $Seconds --reset-minutes $Reset --skip-clocks --touch-power --thermal-log 10 --framebuffer-height $FramebufferHeight $(if ($TourShots) { '--tour-shots','--tour-verify' }) $(if ($Framebuffer) { '--framebuffer' }) $(if ($MonitorIdle -ge 0) { '--monitor-idle',$MonitorIdle }) 2>&1 | Out-File -FilePath "$e\$Log" -Encoding utf8
"monitor_exit=$LASTEXITCODE" | Out-File -FilePath "$e\$Log" -Append -Encoding utf8
