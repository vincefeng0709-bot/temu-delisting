# temu-delisting

自动化 Temu 卖家中心「合规中心 → 违规处理」页面里符合条件的违规商品下架操作。

流程分两步、中间有人工审核闸门，不会全自动直接提交下架：

1. `scan`：登录并抓取指定时间区间内的违规商品，按已知违规类型清单打标"建议下架/待人工判断"，导出一份清单供你审核。
2. `apply`：读取你审核确认过的清单，走客服自助工具流程逐个 SKC ID 提交下架申请。

## 安装

```bash
pip install -e ".[dev]"
playwright install chrome
cp .env.example .env
```

## 首次登录（重要：不能在自动化浏览器里直接登录）

实测 Temu 卖家中心会拦截 Playwright 驱动的浏览器发起的登录请求（提示"账号异常，无法登录"），哪怕是人工手动输入账号密码、哪怕用的是真实 Chrome 内核也一样；换成无痕窗口都能登录，只有 Playwright 自动化的窗口不行——说明这是针对自动化特征的拦截，不是账号或环境问题。本工具**不会**去做绕过/伪装这类反自动化检测的事情，所以登录必须走下面这条路：

1. 在你**平时正常使用的 Chrome**（不是本工具弹出的那个窗口）里登录卖家中心：`https://seller.kuajingmaihuo.com`
2. 装一个 Cookie 导出扩展（比如 "Cookie-Editor"），在已登录的页面上导出该站点 Cookie 为 JSON 文件
3. 运行：
   ```bash
   temu-delisting import-cookies <导出的json文件路径>
   ```
4. 之后 `scan` / `apply` 会直接复用这个登录态，不会再尝试登录

登录态过期后（`scan`/`apply` 会报错提示），重复上面 1-3 步重新导入一次即可。

## 使用

```bash
# 第一步：扫描指定日期区间的违规商品，生成待审核清单
temu-delisting scan --start "2026-08-06" --end "2026-08-07"

# 清单会输出到 data/exports/，逐条在终端确认要不要下架
# （对于"待人工判断"的未知违规类型，请谨慎确认）

# 第二步：执行已确认的下架清单
temu-delisting apply --batch <scan 命令输出的批次ID>

# 先用 --dry-run 走到"申请下架"前一步，不真正提交，用于验证流程走对了
temu-delisting apply --batch <批次ID> --dry-run
```

## 数据与日志

- `data/app.db`：SQLite，记录每个 SKC ID 的处理状态（幂等去重用）
- `data/exports/`：每次 scan 生成的建议清单
- 失败/超时的 SKC 会单独记录，需要人工去卖家中心确认实际状态

## 安全说明

- 账号密码只放在本地 `.env`，不会入库、不会被程序自动重试登录
- 不做验证码/滑块绕过，也不做反自动化检测绕过；登录必须在正常浏览器里人工完成，再导入 Cookie 复用
- 导出的 Cookie JSON 文件包含登录凭据，用完建议删掉，不要提交进 git（`data/` 目录已在 `.gitignore` 里）
- 下架属于不可逆操作，`scan` 只生成建议清单，实际提交前必须经过人工确认
