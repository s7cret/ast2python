#!/usr/bin/env python3
"""Run Stage C P4 with a minimal same-symbol 15m -> D data provider."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import subprocess
import sys
import traceback
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("PINE_STACK_ROOT", Path.home())).expanduser().resolve()
WORKSPACE = ROOT / "[workspace-root]/workspace/btcusdt_v6_stage_c_current"
AST2PYTHON = ROOT / "ast2python"
PINE2AST = ROOT / "pine2ast"
PINELIB = ROOT / "pinelib"
PYTHON = PINE2AST / ".venv/bin/python"
DAY_MS = 86_400_000
M15_MS = 15 * 60 * 1000

from dataclasses import dataclass, field
from pinelib.core import Bar, PineRuntime, SymbolInfo, TimeframeInfo, is_na, na
from pinelib.request import InMemoryDataProvider

# Long OHLCV for prehistory loading
LONG_OHLCV = ROOT / "[workspace-root]/workspace/pine_strategy_harness/data/btcusdt_15m_20240101_20260510_binance.csv"


@dataclass
class MTFPrehistoryConfig:
    """Configuration for MTF prehistory loading."""
    requested_timeframe: str = "D"
    warmup_bars: int = 250
    include_previous_confirmed: bool = True


# Timeframe periods in milliseconds
TF_PERIODS = {
    "1": 60_000,
    "5": 300_000,
    "15": 900_000,
    "60": 3_600_000,
    "240": 14_400_000,
    "D": 86_400_000,
    "W": 604_800_000,
}


def calculate_mtf_prehistory_start(
    target_start_ms: int,
    requested_timeframe: str,
    warmup_bars: int,
    include_previous_confirmed: bool,
) -> int:
    """
    Calculate the start timestamp for MTF prehistory loading.
    
    Args:
        target_start_ms: Chart start timestamp in ms
        requested_timeframe: HTF to load (e.g., "D", "60")
        warmup_bars: Number of HTF bars to load before target
        include_previous_confirmed: Include previous confirmed HTF bar
    
    Returns:
        Start timestamp in ms for loading base bars
    """
    tf_period = TF_PERIODS.get(requested_timeframe, 86_400_000)
    
    # Calculate how many bars we need
    bars_needed = warmup_bars + (1 if include_previous_confirmed else 0)
    
    # Calculate prehistory duration in ms
    prehistory_ms = bars_needed * tf_period
    
    # For D bars, we need to extend to full day boundaries
    # because we aggregate from 15m bars
    # Each D bar needs 96 x 15m bars = 86,400,000 ms
    if requested_timeframe == "D":
        # We load 15m bars, so extend by full days
        # The prehistory in days = bars_needed * D period / DAY_MS
        days_needed = bars_needed
        prehistory_ms = days_needed * 86_400_000
    
    return target_start_ms - prehistory_ms


def load_with_mtf_prehistory(
    symbol: str,
    base_tf: str,
    target_start_ms: int,
    target_end_ms: int,
    config: MTFPrehistoryConfig,
) -> dict[str, list[Bar]]:
    """
    Load base timeframe bars plus aggregated HTF bars with prehistory.
    
    Args:
        symbol: Trading symbol
        base_tf: Base timeframe (e.g., "15")
        target_start_ms: Target window start in ms
        target_end_ms: Target window end in ms
        config: MTF prehistory configuration
    
    Returns:
        Dict with "base" and "htf" keys containing bars
    """
    # Calculate prehistory start
    prehistory_start = calculate_mtf_prehistory_start(
        target_start_ms,
        config.requested_timeframe,
        config.warmup_bars,
        config.include_previous_confirmed,
    )
    
    # Load 15m bars from long OHLCV
    all_bars = []
    if LONG_OHLCV.exists():
        with LONG_OHLCV.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                raw_time = int(float(row["time"]))
                time_ms = raw_time * 1000 if raw_time < 10_000_000_000 else raw_time
                
                # Only load bars within our range
                if time_ms < prehistory_start:
                    continue
                if time_ms > target_end_ms:
                    break
                
                all_bars.append(
                    Bar(
                        time=time_ms,
                        time_close=time_ms + M15_MS - 1,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume", 0) or 0),
                    )
                )
    
    if not all_bars:
        raise ValueError(f"No bars loaded from {LONG_OHLCV}")
    
    # Aggregate to D bars if needed
    if config.requested_timeframe == "D":
        daily_bars = aggregate_daily(all_bars)
    else:
        daily_bars = []
    
    # Extract chart bars (within target window)
    chart_bars = [b for b in all_bars if b.time >= target_start_ms]
    
    return {
        "base": chart_bars,
        "htf": daily_bars,
        "all_15m": all_bars,
        "d_bars": daily_bars,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pine", default=str(WORKSPACE / "02_PINE/oracle_max_part4_mtf_strategy.pine"))
    parser.add_argument("--tv-csv", default=str(WORKSPACE / "00_INPUT/tv_pine_oracle_max_v6.csv"))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--symbol", default="BINANCE:BTCUSDT")
    parser.add_argument("--chart-timeframe", default="15")
    parser.add_argument(
        "--engine",
        default=None,
        help="Optional engine input override. Use 'None' to isolate MTF plots from strategy orders.",
    )
    parser.add_argument("--compare-dir", default=str(WORKSPACE / "04_COMPARE"))
    parser.add_argument(
        "--mtf-warmup",
        type=int,
        default=None,
        help="MTF prehistory warmup bars (e.g., 250). If set, uses long OHLCV for auto prehistory.",
    )
    return parser.parse_args()


def run_cmd(cmd: list[str], *, cwd: Path, log_path: Path) -> None:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr}")


def to_float(value: str | None) -> float:
    if value in (None, ""):
        return math.nan
    return float(value)


def load_15m_bars(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            raw_time = int(float(row["time"]))
            time_ms = raw_time * 1000 if raw_time < 10_000_000_000 else raw_time
            volume_raw = row.get("volume") or row.get("Volume") or row.get("P1_SRC_VOLUME") or "0"
            bars.append(
                Bar(
                    time=time_ms,
                    time_close=time_ms + M15_MS - 1,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(volume_raw or 0.0),
                )
            )
    return bars


def aggregate_daily(bars: list[Bar]) -> list[Bar]:
    buckets: dict[int, list[Bar]] = defaultdict(list)
    for bar in bars:
        buckets[(bar.time // DAY_MS) * DAY_MS].append(bar)

    daily: list[Bar] = []
    for day_open in sorted(buckets):
        group = buckets[day_open]
        daily.append(
            Bar(
                time=day_open,
                time_close=day_open + DAY_MS - 1,
                open=group[0].open,
                high=max(bar.high for bar in group),
                low=min(bar.low for bar in group),
                close=group[-1].close,
                volume=sum(bar.volume for bar in group),
            )
        )
    return daily


def import_generated(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("oracle_v6_p4_mtf", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import generated module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def value_to_cell(value: Any) -> str:
    if value is None or is_na(value):
        return ""
    if isinstance(value, bool):
        return "1.0" if value else "0.0"
    if isinstance(value, int | float):
        if isinstance(value, float) and math.isnan(value):
            return ""
        return repr(float(value))
    return str(value)


from pinelib.plot import PlotRecorder

def visual_rows(script: Any, bars: list[Bar]) -> tuple[list[str], list[dict[str, str]]]:
    recorder = script.rt.plot_recorder
    if isinstance(recorder, PlotRecorder):
        records = recorder.get_records()
    else:
        records = script.visual_calls  # legacy fallback
    if not bars:
        return list(), list()
    if len(records) % len(bars) != 0:
        raise RuntimeError(f"visual event count {len(records)} is not divisible by bars {len(bars)}")
    per_bar = len(records) // len(bars)
    first_chunk = records[:per_bar]
    # Support both PlotRecord (new) and dict (legacy)
    def get_title(rec):
        if hasattr(rec, 'title'):
            return str(rec.title)
        return str(rec.get("args", ())[1] if len(rec.get("args", ())) > 1 else rec.get("kwargs", {}).get("title", ""))
    def get_name(rec):
        if hasattr(rec, 'name'):
            return rec.name
        return rec.get("name", "")
    def get_value(rec):
        if hasattr(rec, 'value'):
            return rec.value
        return rec.get("args", ())[0] if rec.get("args") else None
    columns = [get_title(r) for r in first_chunk if get_name(r) == "plot"]
    rows: list[dict[str, str]] = []
    for index, bar in enumerate(bars):
        row: dict[str, str] = {
            "time": str(bar.time // 1000),
            "open": repr(bar.open),
            "high": repr(bar.high),
            "low": repr(bar.low),
            "close": repr(bar.close),
            "volume": repr(bar.volume),
        }
        chunk = records[index * per_bar : (index + 1) * per_bar]
        for rec in chunk:
            if get_name(rec) != "plot":
                continue
            row[get_title(rec)] = value_to_cell(get_value(rec))
        rows.append(row)
    return ["time", "open", "high", "low", "close", "volume", *columns], rows


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compare_p4(tv_csv: Path, py_csv: Path, compare_root: Path) -> dict[str, Any]:
    with tv_csv.open(newline="", encoding="utf-8-sig") as fh:
        tv_rows = list(csv.DictReader(fh))
        tv_header = tv_rows[0].keys() if tv_rows else []
    with py_csv.open(newline="", encoding="utf-8") as fh:
        py_rows = list(csv.DictReader(fh))
        py_header = py_rows[0].keys() if py_rows else []

    py_by_time = {row["time"]: row for row in py_rows}
    joined = [(row, py_by_time[row["time"]]) for row in tv_rows if row.get("time") in py_by_time]
    columns = sorted(col for col in tv_header if col.startswith("P4_") and col in py_header)
    result: dict[str, Any] = {"joined_rows": len(joined), "columns": columns, "warmups": {}}

    for warmup in (0, 50, 250):
        out_dir = compare_root / f"official_compare_p4_mtf_warmup_{warmup}"
        out_dir.mkdir(parents=True, exist_ok=True)
        summary_rows: list[dict[str, Any]] = []
        mismatch_rows: list[dict[str, Any]] = []
        sample = joined[warmup:]
        for col in columns:
            bad = 0
            max_diff = 0.0
            for tv_row, py_row in sample:
                tv_raw = tv_row.get(col, "")
                py_raw = py_row.get(col, "")
                tv_empty = tv_raw in ("", None)
                py_empty = py_raw in ("", None)
                diff = 0.0
                matched = tv_empty and py_empty
                if not matched and tv_empty != py_empty:
                    matched = False
                    diff = math.inf
                elif not matched:
                    tv_val = to_float(tv_raw)
                    py_val = to_float(py_raw)
                    diff = abs(tv_val - py_val)
                    matched = math.isclose(tv_val, py_val, rel_tol=1e-9, abs_tol=1e-6)
                if not matched:
                    bad += 1
                    max_diff = math.inf if diff == math.inf else max(max_diff, diff)
                    if len(mismatch_rows) < 500:
                        mismatch_rows.append(
                            {
                                "time": tv_row["time"],
                                "column": col,
                                "tv": tv_raw,
                                "py": py_raw,
                                "diff": "inf" if diff == math.inf else repr(diff),
                            }
                        )
            summary_rows.append(
                {
                    "column": col,
                    "rows": len(sample),
                    "bad": bad,
                    "max_diff": "inf" if max_diff == math.inf else repr(max_diff),
                    "status": "MATCH" if bad == 0 else "MISMATCH",
                }
            )

        write_csv(
            out_dir / "oracle_compare_summary.csv",
            ["column", "rows", "bad", "max_diff", "status"],
            summary_rows,
        )
        write_csv(
            out_dir / "oracle_compare_mismatches.csv",
            ["time", "column", "tv", "py", "diff"],
            mismatch_rows,
        )
        bad_columns = sum(1 for row in summary_rows if row["bad"])
        result["warmups"][str(warmup)] = {
            "path": str(out_dir),
            "columns": len(summary_rows),
            "bad_columns": bad_columns,
        }
    return result


def main() -> int:
    args = parse_args()
    pine_path = Path(args.pine)
    tv_csv = Path(args.tv_csv)
    out_dir = Path(args.out_dir)
    logs_dir = out_dir / "logs"
    modules_dir = out_dir / "modules/p4"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    modules_dir.mkdir(parents=True, exist_ok=True)

    ast_path = out_dir / "oracle_v6_p4.ast.json"
    generated_py = modules_dir / "oracle_v6_p4.py"

    run_cmd(
        [str(PYTHON), "-m", "pine2ast", "parse", str(pine_path), "--json", str(ast_path), "--runtime-contract-v1-4"],
        cwd=PINE2AST,
        log_path=logs_dir / "p4_parse.log",
    )
    run_cmd(
        [
            str(PYTHON),
            "-m",
            "ast2python.cli.main",
            "translate",
            str(ast_path),
            "-o",
            str(modules_dir),
            "--module-name",
            "oracle_v6_p4",
            "--allow-invalid-ast",
        ],
        cwd=AST2PYTHON,
        log_path=logs_dir / "p4_translate.log",
    )

    # Load bars - either with MTF prehistory or simple TV CSV
    if args.mtf_warmup is not None:
        # Use MTF prehistory loader
        mtf_config = MTFPrehistoryConfig(
            requested_timeframe="D",
            warmup_bars=args.mtf_warmup,
            include_previous_confirmed=True,
        )
        # Get target window from TV CSV
        tv_bars = load_15m_bars(tv_csv)
        target_start = tv_bars[0].time
        target_end = tv_bars[-1].time_close or tv_bars[-1].time
        
        # Load with prehistory
        loaded = load_with_mtf_prehistory(
            args.symbol,
            args.chart_timeframe,
            target_start,
            target_end,
            mtf_config,
        )
        bars = loaded["base"]  # Chart bars within target window
        daily_bars = loaded["d_bars"]  # Aggregated D bars
        provider = InMemoryDataProvider(
            {
                (args.symbol, args.chart_timeframe): bars,
                (args.symbol, "D"): daily_bars,
            }
        )
    else:
        # Simple mode - just TV CSV bars
        bars = load_15m_bars(tv_csv)
        daily_bars = aggregate_daily(bars)
        provider = InMemoryDataProvider(
            {
                (args.symbol, args.chart_timeframe): bars,
                (args.symbol, "D"): daily_bars,
            }
        )
    runtime = PineRuntime(
        SymbolInfo(tickerid=args.symbol, timezone="UTC", session="0000-2359"),
        TimeframeInfo.from_string(args.chart_timeframe),
        data_provider=provider,
    )
    module = import_generated(generated_py)
    params = {"engine": args.engine} if args.engine is not None else {}
    script = module.GeneratedStrategy(params=params, runtime=runtime)

    execute_status: dict[str, Any]
    try:
        snapshots = script.run(bars)
        header, rows = visual_rows(script, bars)
        generated_csv = out_dir / "generated_oracle_v6_BTCUSDT_15m_p4_mtf.csv"
        write_csv(generated_csv, header, rows)
        execute_status = {
            "status": "OK",
            "rows": len(rows),
            "snapshots": len(snapshots),
            "generated_csv": str(generated_csv),
            "plot_cols": len([col for col in header if col.startswith("P4_")]),
        }
    except Exception as exc:  # pragma: no cover - artifact runner path
        (logs_dir / "p4_execute.stderr").write_text(traceback.format_exc(), encoding="utf-8")
        execute_status = {"status": "FAIL", "error": repr(exc), "traceback": str(logs_dir / "p4_execute.stderr")}

    daily_rows = [
        {
            "time": str(bar.time),
            "time_iso": datetime.fromtimestamp(bar.time / 1000, UTC).isoformat(),
            "time_close": str(bar.time_close or ""),
            "open": repr(bar.open),
            "high": repr(bar.high),
            "low": repr(bar.low),
            "close": repr(bar.close),
            "volume": repr(bar.volume),
        }
        for bar in daily_bars
    ]
    write_csv(
        out_dir / "daily_bars.csv",
        ["time", "time_iso", "time_close", "open", "high", "low", "close", "volume"],
        daily_rows,
    )

    compare: dict[str, Any] | None = None
    if execute_status["status"] == "OK":
        compare = compare_p4(tv_csv, Path(execute_status["generated_csv"]), Path(args.compare_dir))

    summary = {
        "parse": "OK",
        "translate": "OK",
        "execute": execute_status,
        "daily_bars": {
            "count": len(daily_bars),
            "first": daily_rows[0] if daily_rows else None,
            "last": daily_rows[-1] if daily_rows else None,
        },
        "provider_keys": sorted(f"{symbol}:{tf}" for symbol, tf in provider._bars_by_key),  # noqa: SLF001
        "compare": compare,
    }
    (out_dir / "p4_mtf_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if execute_status["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
