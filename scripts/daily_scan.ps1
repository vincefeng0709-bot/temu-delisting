# 手动运行用：跑一次 scan，抓取"昨天"这一天的违规商品，生成待审核清单。
#
# 本来想接成 Windows 计划任务每天自动跑，但实测 Task Scheduler 触发的进程
# 没法在你能看到的那个桌面会话里弹出浏览器窗口（哪怕换成弹一个最简单的提示
# 框也一样弹不出来，进程本身是活的，只是画面出不来），这是 Windows
# 计划任务这个机制本身的会话隔离限制，不是代码问题，所以放弃自动定时。
# 这个脚本留着当手动快捷方式用：想跑当天的 scan 时，双击它或者在
# PowerShell 里执行一下就行，不用自己去算日期、敲长命令。
#
# 只自动了 scan（数据抓取），review 确认和 apply 提交下架还是要你自己手动
# 跑 —— 这道人工确认闸门本来就不该被自动化绕过。

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

& "$ProjectRoot\.venv\Scripts\Activate.ps1"

$yesterday = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")

Write-Host "[daily_scan] 扫描日期: $yesterday"
temu-delisting scan --start $yesterday --end $yesterday --no-review
