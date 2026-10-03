<#
.SYNOPSIS
  在「主仓库」与「第四幕洁净环境」之间切换 AGH 的 eeg-agent MCP 注册。

.DESCRIPTION
  第四幕要求 agent 看到的是洁净环境那 10 个工具（没有三个试验台工具），产物写进
  本次运行的独立产物根。AGH 不给 stdio MCP 传环境变量，所以只能换注册路径——
  这是第四幕唯一躲不掉的手工步骤，也是第一次试跑废掉的原因（工作区与技能都换对了，
  只漏了这里）。

  改注册是写操作，AGH 强制交互确认，所以必须在**真实的 PowerShell 窗口**里跑。

.EXAMPLE
  # 跑第四幕之前：切到洁净环境
  .\scripts\act4_switch_mcp.ps1 -Target clean

.EXAMPLE
  # 第四幕跑完：切回主仓库（**必须换回来**，否则后续三幕的证据核对会错位）
  .\scripts\act4_switch_mcp.ps1 -Target main
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('clean', 'main')]
    [string]$Target,

    [string]$Cli = 'D:\AI-tools\agnes-harness-main\packages\cli\dist\local\agnes.mjs',
    [string]$ServerId = 'eeg-agent'
)

$ErrorActionPreference = 'Stop'

$targets = @{
    'clean' = @{
        Exe  = 'D:/eeg-agent-work/env/.venv/Scripts/python.exe'
        Srv  = 'D:/eeg-agent-work/env/tools/eeg_mcp_server.py'
        Want = '10 个工具（无零信号试验台三工具）'
    }
    'main'  = @{
        Exe  = 'D:/暂存/source/.venv/Scripts/python.exe'
        Srv  = 'D:/暂存/source/tools/eeg_mcp_server.py'
        Want = '13 个工具（含试验台三工具）'
    }
}

$t = $targets[$Target]

if (-not (Test-Path $Cli)) { throw "找不到 AGH CLI：$Cli" }
if (-not (Test-Path $t.Exe)) { throw "解释器不存在：$($t.Exe)" }
if (-not (Test-Path $t.Srv)) { throw "MCP server 不存在：$($t.Srv)" }

# 每次写操作都会改 revision，所以每一步之前都要**重新读一次**，不能复用旧值。
function Get-Rev {
    $out = (node $Cli mcp get $ServerId | Out-String)
    if ($out -notmatch 'revision=([0-9a-f]{8,})') {
        throw "读不到 revision，mcp get 输出：`n$out"
    }
    return $Matches[1]
}

Write-Host "── 切到「$Target」──────────────────────────────"
Write-Host "  解释器 : $($t.Exe)"
Write-Host "  server : $($t.Srv)"
Write-Host "  预期   : $($t.Want)"
Write-Host ""

$rev = Get-Rev
Write-Host "[1/4] mcp update  (revision=$($rev.Substring(0,12))…)"
node $Cli mcp update $ServerId --expected-revision $rev --name $ServerId `
    --stdio $t.Exe --arg $t.Srv

$rev = Get-Rev
Write-Host "[2/4] mcp trust   (revision=$($rev.Substring(0,12))…)  ← 改了命令，信任要重签"
node $Cli mcp trust $ServerId --expected-revision $rev

$rev = Get-Rev
Write-Host "[3/4] mcp enable  (revision=$($rev.Substring(0,12))…)"
node $Cli mcp enable $ServerId --expected-revision $rev

Write-Host "[4/4] mcp tools   ← 核对工具数"
node $Cli mcp tools $ServerId

Write-Host ""
Write-Host "── 完毕 ──────────────────────────────────────"
Write-Host "确认上面列出的工具数与「$($t.Want)」一致。"
if ($Target -eq 'clean') {
    Write-Host ""
    Write-Host "下一步：开一条一次性会话，确认 eeg_artifacts 的 cache_dir 是"
    Write-Host "        D:\eeg-agent-data\runs\run-NN\v1（不是 %LOCALAPPDATA% 下的默认根）。"
} else {
    Write-Host ""
    Write-Host "已换回主仓库。记得把默认台账也还原（见 runbook-act4.md §1.5）。"
}
