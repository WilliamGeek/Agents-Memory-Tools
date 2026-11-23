$ErrorActionPreference = 'SilentlyContinue'

$TauriProcesses = Get-CimInstance Win32_Process -Filter "Name='agents-memory-tools-desktop.exe'"
if ($TauriProcesses) {
    Write-Host '桌面版正在运行；请关闭桌面版窗口，不要单独结束后台 sidecar。'
    exit 0
}

$ports = @(18923, 18922)
$stopped = @()
foreach ($port in $ports) {
    $lines = netstat -ano | Select-String ":$port " | Select-String 'LISTENING'
    foreach ($line in $lines) {
        $pidText = ($line.Line -split '\s+')[-1]
        if ($pidText -match '^\d+$' -and [int]$pidText -ne 0) {
            $proc = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -in @('memory-tools', 'python', 'pythonw')) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $stopped += "port $port / PID $($proc.Id) / $($proc.ProcessName)"
            }
        }
    }
}

if ($stopped.Count -gt 0) {
    $stopped | ForEach-Object { Write-Host "已停止：$_" }
} else {
    Write-Host '没有发现由网页版启动的后台进程。'
}
