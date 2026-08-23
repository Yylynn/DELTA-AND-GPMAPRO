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

OpenD 行情功能还需要 Futu Python SDK。上述安装命令会自动安装它；若页面提示 `Futu Python SDK is not installed`，说明后端不是由项目启动脚本使用的虚拟环境启动。关闭该后端后重新运行 `02_启动开发版.bat`，或在实际运行后端的环境中执行：

```powershell
cd backend
..\.venv-local\Scripts\python.exe -m pip install -e .[dev]
```

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest
cd frontend
npm run build
```
