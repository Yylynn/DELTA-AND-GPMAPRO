import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.data import futu_snapshots, market_snapshots, provider
from app.services.market_snapshot import MarketDataError
from app.services.backtest_datasets import BacktestDatasetCatalog
from app.services.backtest_rule_engine import BacktestRuleEngine
from app.services.backtest_signal_preview import BacktestSignalPreviewService


router = APIRouter(tags=["backtest-datasets"])
catalog = BacktestDatasetCatalog(provider, futu_snapshots, market_snapshots)
preview_service = BacktestSignalPreviewService(catalog)
rule_engine = BacktestRuleEngine(preview_service)


_BACKTEST_SIGNAL_LABELS = {
    "BOTTOM_FACE": "底部一级背离",
    "TOP_FACE": "顶部一级背离",
    "BOTTOM_ARROW_2": "底部二级背离",
    "TOP_ARROW_2": "顶部二级背离",
    "BOTTOM_ARROW_3": "底部三级背离",
    "TOP_ARROW_3": "顶部三级背离",
}


def _signal_label(code: str) -> str:
    if code.startswith("V1_"):
        version, signal = "第一版", code[3:]
    elif code.startswith("V2_"):
        version, signal = "第二版", code[3:]
    else:
        return _BACKTEST_SIGNAL_LABELS.get(code, code)
    if signal in _BACKTEST_SIGNAL_LABELS:
        return _BACKTEST_SIGNAL_LABELS[signal]
    return f"{version} {_BACKTEST_SIGNAL_LABELS.get(signal, signal)}"


class BacktestDatasetLoadRequest(BaseModel):
    dataset_ids: list[str] = Field(min_length=1, max_length=20)


class BacktestSymbolLoadRequest(BaseModel):
    code: str = Field(min_length=1)
    refresh: bool = False


class BacktestSignalPreviewRequest(BaseModel):
    dataset_id: str = Field(min_length=1)
    years: int = Field(default=2, ge=1, le=2)


class BacktestRuleRunRequest(BaseModel):
    dataset_id: str = Field(min_length=1)
    buy_signals: list[str] = Field(min_length=1)
    sell_signals: list[str] = Field(min_length=1)
    start_date: str | None = None
    end_date: str | None = None
    initial_capital: float = Field(default=100_000.0, gt=0)
    commission_bps_per_side: float = Field(default=5.0, ge=0, le=500)
    slippage_bps_per_side: float = Field(default=5.0, ge=0, le=500)
    max_holding_bars: int = Field(default=60, ge=1, le=500)


@router.get("/backtest/datasets")
def backtest_datasets():
    try:
        datasets = catalog.list()
        return {
            "datasets": datasets,
            "counts": {
                "local_csv": sum(item["source"] == "local_csv" for item in datasets),
                "futu_snapshot": sum(item["source"] == "futu_snapshot" for item in datasets),
            },
        }
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.post("/backtest/symbol/load")
def load_backtest_symbol(request: BacktestSymbolLoadRequest):
    try:
        return catalog.load_symbol(request.code, refresh=request.refresh)
    except MarketDataError as error:
        raise HTTPException(503, str(error))
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(422, str(error))


@router.post("/backtest/datasets/load")
def load_backtest_datasets(request: BacktestDatasetLoadRequest):
    try:
        return catalog.load(request.dataset_ids)
    except FileNotFoundError as error:
        raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.post("/backtest/datasets/signal-preview")
def backtest_signal_preview(request: BacktestSignalPreviewRequest):
    try:
        return preview_service.build(request.dataset_id, request.years)
    except FileNotFoundError as error:
        raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.post("/backtest/rules/run")
def run_backtest_rules(request: BacktestRuleRunRequest):
    try:
        return rule_engine.run(**request.model_dump())
    except FileNotFoundError as error:
        raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.post("/backtest/rules/export.csv")
def export_backtest_rules(request: BacktestRuleRunRequest):
    result = run_backtest_rules(request)
    output = io.StringIO()
    writer = csv.writer(output)
    fingerprint = result["run_fingerprint"]
    actions: dict[str, list[str]] = {}
    profit_and_loss: dict[str, float] = {}

    def add_action(date: str, action: str):
        actions.setdefault(date, []).append(action)

    for trade in result["closed_trades"]:
        add_action(
            trade["entry_date"],
            f"买入 {' + '.join(_signal_label(code) for code in trade['entry_signals'])}",
        )
        exit_label = (
            " + ".join(_signal_label(code) for code in trade["exit_signals"])
            if trade["exit_signals"]
            else "最大持有期限"
        )
        add_action(trade["exit_date"], f"卖出 {exit_label}")
        profit_and_loss[trade["exit_date"]] = float(trade["pnl"])

    open_position = result.get("open_position")
    if open_position:
        add_action(
            open_position["entry_date"],
            f"买入 {' + '.join(_signal_label(code) for code in open_position['entry_signals'])}",
        )
        add_action(open_position["last_date"], "持仓中（未实现）")
        profit_and_loss[open_position["last_date"]] = float(open_position["unrealized_pnl"])

    writer.writerow(["时间", "资金", "操作", "盈利/亏损"])
    for row in result["equity_curve"]:
        pnl = profit_and_loss.get(row["date"])
        writer.writerow([
            row["date"],
            f"{float(row['equity']):.2f}",
            "；".join(actions.get(row["date"], [])),
            "" if pnl is None else f"{pnl:+.2f}",
        ])
    filename = f"backtest-{result['dataset']['symbol'].replace('.', '-')}-{fingerprint[:12]}.csv"
    payload = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Backtest-Fingerprint": fingerprint,
        },
    )
