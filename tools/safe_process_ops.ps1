# 进程操作安全门禁（AGENTS / 人工共用）
#
# 目的：在崩溃取证与 AI 工具运维中，杜绝「误杀系统关键进程」。
# 用法：
#   .\safe_process_ops.ps1                          # 基线巡检（只读）
#   .\safe_process_ops.ps1 -Mode Preview -Name svchost
#   .\safe_process_ops.ps1 -Mode Stop -Id 12345 -Reason "用户批准关闭某子进程"
#   .\safe_process_ops.ps1 -Mode Stop -Name Doubao -Reason "..." -AllowAppTarget
#
# 规则：
#   1. 受保护名单内进程（System/Registry/smss/csrss/wininit/services/lsass/winlogon/svchost/dwm/explorer 等）永远拒绝终止；
#   2. Session 0 内进程、当前 Shell 的祖先链，一律拒绝；
#   3. Doubao.exe / Trae CN.exe / web_app.py 视为「进行中的业务进程」，需 -AllowAppTarget 才可进入终止流程；
#   4. 默认 Preview（只打印不执行），只有 -Mode Stop 才真正终止；
#   5. 所有判定与执行结果写入 logs\process_ops.log 审计。

param(
    [ValidateSet('Baseline', 'Preview', 'Stop')]
    [string]$Mode = 'Baseline',
    [int[]]$Id = @(),
    [string[]]$Name = @(),
    [string]$Reason = '未填写原因',
    [switch]$AllowAppTarget,
    [string]$LogPath = ""
)

$ErrorActionPreference = 'Stop'

if (-not $LogPath) {
    $LogPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\process_ops.log'
}
$logDir = Split-Path -Parent $LogPath
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$ProtectedNames = @(
    'System', 'Registry', 'Memory Compression', 'Idle',
    'smss', 'csrss', 'wininit', 'services', 'lsass', 'winlogon', 'userinit',
    'svchost', 'fontdrvhost', 'dwm', 'sihost', 'ctfmon', 'explorer',
    'ShellExperienceHost', 'StartMenuExperienceHost', 'SearchHost', 'TextInputHost',
    'LogonUI', 'spoolsv', 'audiodg', 'WUDFHost',
    'MsMpEng', 'NisSrv', 'SecurityHealthService', 'Sense'
)
$BusinessProcessNames = @('Doubao', 'Trae CN', 'web_app')

function Write-Audit {
    param([string]$Line)
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$ts`t$env:USERNAME`t$Line" | Add-Content -Path $LogPath -Encoding UTF8
}

$script:ProcTable = @{}
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object { $script:ProcTable[[int]$_.ProcessId] = $_ }

function Get-AncestorIds {
    $ids = @()
    $cur = $PID
    for ($i = 0; $i -lt 12 -and $cur) {
        $ids += $cur
        $p = $script:ProcTable[[int]$cur]
        if (-not $p) { break }
        $cur = [int]$p.ParentProcessId
    }
    return $ids
}
$script:SelfChain = Get-AncestorIds

function Get-ProcessFacts {
    param([int]$ProcessId)
    $script:ProcTable[[int]$ProcessId]
}

function Test-TargetProtected {
    param($Facts)
    $reasons = @()
    if ($ProtectedNames -contains $Facts.Name) { $reasons += '受保护名单' }
    if ($Facts.SessionId -eq 0) { $reasons += 'Session0' }
    $selfChain = $script:SelfChain
    if ($selfChain -contains $Facts.ProcessId) { $reasons += '当前Shell祖先链' }
    $parent = Get-ProcessFacts -ProcessId $Facts.ParentProcessId
    if ($parent -and ($parent.Name -in @('services.exe', 'wininit.exe', 'csrss.exe', 'smss.exe'))) {
        $reasons += "父进程为$($parent.Name)"
    }
    $appTarget = $false
    foreach ($b in $BusinessProcessNames) {
        if ($Facts.Name -like "$b*" -or ($Facts.CommandLine -and $Facts.CommandLine -like "*$b*")) { $appTarget = $true; break }
    }
    [pscustomobject]@{ Protected = ($reasons.Count -gt 0); Reasons = ($reasons -join '; '); BusinessTarget = $appTarget }
}

function Show-Baseline {
    $must = @('csrss', 'wininit', 'services', 'lsass', 'smss', 'winlogon', 'svchost', 'explorer', 'dwm')
    $bad = @()
    foreach ($n in $must) {
        $c = (Get-Process -Name $n -ErrorAction SilentlyContinue | Measure-Object).Count
        '{0,-10} count={1}' -f $n, $c
        if ($c -eq 0) { $bad += $n }
    }
    if ($bad.Count -gt 0) {
        Write-Audit "BASELINE FAIL missing=$($bad -join ',')"
        Write-Warning "缺失关键进程: $($bad -join ', ')"
        return 2
    }
    Write-Audit 'BASELINE OK'
    return 0
}

if ($Mode -eq 'Baseline') {
    exit (Show-Baseline)
}

if ($Id.Count -eq 0 -and $Name.Count -eq 0) {
    Write-Warning '请用 -Id 或 -Name 指定目标；Baseline 模式不需要目标。'
    exit 1
}

$targets = @()
if ($Id.Count -gt 0) {
    foreach ($i in $Id) {
        $f = Get-ProcessFacts -ProcessId $i
        if ($f) { $targets += $f } else { Write-Warning "PID $i 不存在" }
    }
}
foreach ($n in $Name) {
    $procs = Get-Process -Name $n -ErrorAction SilentlyContinue
    if (-not $procs) { Write-Warning "未找到名为 $n 的进程"; continue }
    foreach ($p in $procs) {
        $f = Get-ProcessFacts -ProcessId $p.Id
        if ($f) { $targets += $f }
    }
}

if ($targets.Count -eq 0) { Write-Audit "TARGET-NONE mode=$Mode name=$($Name -join ',')"; exit 1 }

$exit = 0
foreach ($t in $targets) {
    $verdict = Test-TargetProtected -Facts $t
    $line = "PID=$($t.ProcessId) NAME=$($t.Name) SESSION=$($t.SessionId) PROTECTED=$($verdict.Protected) REASON=$($verdict.Reasons) MODE=$Mode WHY=$Reason"
    if ($verdict.Protected) {
        Write-Audit "REFUSE $line"
        Write-Warning "拒绝终止：$($t.Name) (PID $($t.ProcessId)) — $($verdict.Reasons)"
        $exit = 2
        continue
    }
    if ($verdict.BusinessTarget -and -not $AllowAppTarget) {
        Write-Audit "REFUSE-APP $line"
        Write-Warning "拒绝终止业务进程：$($t.Name) (PID $($t.ProcessId))，如确需请加 -AllowAppTarget"
        $exit = 3
        continue
    }
    if ($Mode -eq 'Preview') {
        Write-Audit "PREVIEW $line"
        Write-Host "[Preview] 可终止（未执行）: $($t.Name) PID=$($t.ProcessId) Path=$($t.ExecutablePath)"
        continue
    }
    # Stop
    try {
        Stop-Process -Id $t.ProcessId -Force -ErrorAction Stop
        Write-Audit "STOPPED $line"
        Write-Host "[Stopped] $($t.Name) PID=$($t.ProcessId)"
    } catch {
        Write-Audit "FAIL $line ERR=$($_.Exception.Message)"
        Write-Warning "终止失败：$($_.Exception.Message)"
        $exit = 4
    }
}
exit $exit
