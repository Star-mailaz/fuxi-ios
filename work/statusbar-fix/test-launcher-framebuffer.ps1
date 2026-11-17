$ErrorActionPreference = 'Stop'
$workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$storage = Join-Path $workspace 'work\Codex-Xiaomi13-GPU-20261109'
$launcher = Join-Path $PSScriptRoot 'launch-loader-check.ps1'
$boot = Join-Path $storage 'boot-exp-v.ps1'
$monitor = Join-Path $storage 'run-monitor.ps1'
$syntaxTrees = @{}
foreach ($scriptPath in @($launcher, $boot, $monitor)) {
    $tokens = $null
    $parseErrors = $null
    $syntaxTrees[$scriptPath] = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw "Syntax errors in ${scriptPath}: $parseErrors" }
}
$parameterSets = @(Get-Command -Name $launcher | Select-Object -ExpandProperty ParameterSets)
$inspectSet = $parameterSets | Where-Object Name -eq 'InspectWifi'
$bootSet = $parameterSets | Where-Object Name -eq 'Boot'
if ($parameterSets.Count -ne 2 -or -not $inspectSet -or -not $bootSet) {
    throw 'Missing boot or read-only inspection parameter set'
}
if (($inspectSet.Parameters.Name -contains 'Loader') -or
    ($inspectSet.Parameters.Name -contains 'Dylib') -or
    ($inspectSet.Parameters.Name -contains 'TurnipHybrid') -or
    ($bootSet.Parameters.Name -contains 'InspectWifi')) {
    throw 'Read-only inspection accepts boot or staging parameters'
}
$inspectRequired = @($inspectSet.Parameters | Where-Object IsMandatory | Select-Object -ExpandProperty Name)
if ($inspectRequired.Count -ne 2 -or 'Out' -notin $inspectRequired -or 'InspectWifi' -notin $inspectRequired) {
    throw 'Read-only inspection parameter requirements changed'
}
$launchCommand = $syntaxTrees[$launcher].Find({ param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and $node.Extent.Text.Contains("'boot-exp-v.ps1'")
}, $true)
if (-not $launchCommand) { throw 'Missing guarded boot command' }
$forwarding = $launchCommand.Extent.Text -replace '^&\s+\(Join-Path \$storage ''boot-exp-v.ps1''\)', 'Receive-Flags'
function Receive-Flags {
    param($Loader, $Out, $Kernel, $Seconds, $Reset, $Verifier, [switch]$TourShots, [switch]$Framebuffer, $FramebufferHeight)
    @{ TourShots = [bool]$TourShots; Framebuffer = [bool]$Framebuffer; Height = $FramebufferHeight }
}
$Loader = 'host-fixture'
$Out = 'host-fixture'
$Kernel = 'host-fixture'
$Seconds = 150
$Reset = 4
$FramebufferHeight = 2400
foreach ($final in @($false, $true)) {
    $FinalFramebuffer = $final
    $received = & ([scriptblock]::Create($forwarding))
    if ($received.TourShots -ne (-not $final) -or $received.Framebuffer -ne $final -or $received.Height -ne 2400) {
        throw 'Launcher screenshot forwarding changed'
    }
}
$commandAssignment = $syntaxTrees[$boot].Find({ param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq '$cl'
}, $true)
$monitorExpression = $commandAssignment.Right.Extent.Text -replace '\$e\b', '$storage'
$log = 'host-fixture.log'
$MonitorIdle = -1
foreach ($final in @($false, $true)) {
    $TourShots = -not $final
    $Framebuffer = $final
    $commandLine = & ([scriptblock]::Create($monitorExpression))
    $hasFinalFramebuffer = $commandLine -match '(?:^|\s)-Framebuffer(?:\s|$)'
    if ($hasFinalFramebuffer -ne $final) {
        throw 'Boot wrapper did not forward the final-frame flag'
    }
    if ($commandLine.Contains(' -TourShots') -ne (-not $final)) { throw 'Boot wrapper tour flag changed' }
}
$pythonCommand = $syntaxTrees[$monitor].Find({ param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'python'
}, $true)
if (-not $pythonCommand.Extent.Text.Contains("`$(if (`$Framebuffer) { '--framebuffer' })")) {
    throw 'Monitor wrapper did not forward the Python flag'
}
'PASS: three scripts parse; default tour and final-only framebuffer flags forward without touching the phone'
