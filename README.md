# DELTA 时空交易终端

用于本地 DELTA 时间、GPMAPRO 价格行为和收益验证的 Windows 研究终端；不连接券商、不读取账户、不生成订单。

## 当前能力

- 本地 OHLCV CSV 导入、质量检查、数据新鲜度和标的池资格管理；
- DELTA ITD 时间结构与手工 DELTA 时间窗；
- GPMAPRO EMA、MACD、ATR、成交量、过滤器、B/S 信号和顶底背离的完整可视化；
- DELTA、GPMAPRO、方向一致组合及随机对照的固定持有期事件收益回测；
- 成本后组合资金曲线、回撤、Sharpe、滚动样本外验证和 CSV 导出。

## 研究边界

当前结果是本地历史研究证据，不是实盘收益承诺。多资产泛化验证要求至少 8 个、每个至少 750 根日线的合格标的；未满足该条件时，应将结果视为探索性研究。

## 启动开发版

1. 双击根目录的 `01_环境检查.bat`，确认环境无误。
2. 双击 `02_启动开发版.bat`。

若现有 `.venv` 在 Windows 上无法加载 `asyncio`，请用本机 Python 3.12 创建 `.venv-local`；启动脚本会自动优先使用它：

```powershell
py -3.12 -m venv .venv-local
.\.venv-local\Scripts\python.exe -m pip install -e .\backend[dev]
```

默认行情源为 Yahoo Finance，无需 API Key 或本地行情进程。首次拉取需要联网；行情会保存为带 SHA-256 的本地不可变研究快照。Yahoo/yfinance 仅适合个人研究，请勿把抓取后的行情文件提交到 Git 或重新分发。

如需使用富途 MyLang 公式复算与对账，可选安装 Futu SDK、启动本地 OpenD，并在 `.env` 设置 `DELTA_MARKET_DATA_PROVIDER=futu`：

```powershell
cd backend
..\.venv-local\Scripts\python.exe -m pip install -e .[dev,futu]
```

## 在线部署

仓库包含 `Dockerfile` 和 `render.yaml`，可以将 React 前端与 FastAPI 后端部署为同一个 Render Web Service。线上默认行情源仍为 Yahoo Finance/yfinance，不需要 Futu 或 OpenD。

1. 将包含部署文件的分支推送到自己的 GitHub 仓库，并合并到要部署的分支。
2. 登录 Render，选择 **New > Blueprint**，连接该 GitHub 仓库。
3. Render 会读取根目录的 `render.yaml`；确认服务名称后点击 **Apply**。
4. 部署完成后，打开 Render 给出的 `https://...onrender.com` 地址即可使用；健康检查地址为 `/api/health`。

免费方案首次访问可能需要等待服务唤醒。当前部署不挂载持久磁盘：在线拉取的 yfinance 快照和用户上传的 CSV 可以立即用于研究与回测，但服务重启或重新部署后可能被清除。请保留原始 CSV；如果后续需要长期保存，再接入对象存储或 Render Persistent Disk。

为降低公开演示环境的后台资源占用，`render.yaml` 默认关闭新闻刷新、期权监控和股票池扫描；行情拉取、CSV 数据管理、信号预览和回测实验室不受影响。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest
cd frontend
npm run build
```
