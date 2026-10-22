param([int]$Port = 8877, [string]$Distribution = "Ubuntu")
$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$address = "http://127.0.0.1:$Port"
function Test-Console {
    try {
        $result = Invoke-RestMethod "$address/api/environment" -TimeoutSec 2
        return ($result.service -eq "ripple-lab")
    } catch { return $false }
}
try {
    if (-not (Test-Console)) {
        if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
            throw "需要 WSL2 Ubuntu。请先安装 WSL，并在 Ubuntu 中安装 Java 8、Maven、Python 3、iproute2、tcpdump 和 ethtool。"
        }
        $linuxWorkspace = (& wsl.exe -d $Distribution -u root -- wslpath -u $workspace | Select-Object -Last 1).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $linuxWorkspace.StartsWith("/")) { throw "无法进入 WSL 工作目录。" }
        $logDirectory = Join-Path $PSScriptRoot "launcher-logs"
        New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
        $arguments = @("-d", $Distribution, "-u", "root", "--cd", ('"' + $linuxWorkspace + '"'),
                       "--", "python3", "-m", "ripple_lab.server", "--port", "$Port")
        Start-Process -FilePath "wsl.exe" -ArgumentList $arguments -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logDirectory "server.log") `
            -RedirectStandardError (Join-Path $logDirectory "server-error.log") | Out-Null
        $deadline = (Get-Date).AddSeconds(30)
        while (-not (Test-Console)) {
            if ((Get-Date) -gt $deadline) { throw "服务未能启动，请查看 ripple_lab\launcher-logs\server-error.log。" }
            Start-Sleep -Milliseconds 300
        }
    }
    Start-Process $address
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "按回车关闭"
    exit 1
}
