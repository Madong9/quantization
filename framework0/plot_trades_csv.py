from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def get_closed_time_text(row: dict[str, str]) -> str:
    return row.get("closed_at_bj") or row.get("closed_at_utc") or ""


def load_trade_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    if not rows:
        raise RuntimeError(f"{csv_path} is empty")

    return rows


def build_equity_curve(csv_path: Path, output_path: Path | None = None) -> Path:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("matplotlib is required to draw the equity curve") from exc

    rows = load_trade_rows(csv_path)

    trade_numbers = [0]
    balances = [float(rows[0]["balance_before"])]

    for row in rows:
        trade_numbers.append(int(row["trade_id"]))
        balances.append(float(row["balance_after"]))

    if output_path is None:
        output_path = csv_path.with_name("equity_curve.png")

    plt.figure(figsize=(12, 5))
    plt.plot(trade_numbers, balances, marker="o", linewidth=1.1, markersize=2.6)
    plt.title(f"Equity Curve - {csv_path.stem}")
    plt.xlabel("Closed Trade Number")
    plt.ylabel("Balance (USDT)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()

    return output_path


def build_time_equity_curve(csv_path: Path, output_path: Path | None = None) -> Path:
    try:
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("matplotlib is required to draw the equity curve") from exc

    rows = load_trade_rows(csv_path)

    times = [datetime.fromisoformat(get_closed_time_text(rows[0])).astimezone(timezone.utc)]
    balances = [float(rows[0]["balance_before"])]

    for row in rows:
        times.append(datetime.fromisoformat(get_closed_time_text(row)).astimezone(timezone.utc))
        balances.append(float(row["balance_after"]))

    if output_path is None:
        output_path = csv_path.with_name("equity_curve_time.png")

    plt.figure(figsize=(12, 5))
    plt.plot(times, balances, marker="o", linewidth=1.1, markersize=2.6)
    plt.title(f"Equity Curve by Time - {csv_path.stem}")
    plt.xlabel("Closed Time (UTC)")
    plt.ylabel("Balance (USDT)")
    plt.grid(True, alpha=0.3)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=timezone.utc))
    plt.gcf().autofmt_xdate()
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()

    return output_path


def build_dual_axis_curve(csv_path: Path, output_path: Path | None = None) -> Path:
    try:
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("matplotlib is required to draw the equity curve") from exc

    rows = load_trade_rows(csv_path)

    times = [datetime.fromisoformat(get_closed_time_text(row)).astimezone(BEIJING_TZ) for row in rows]
    balances = [float(row["balance_after"]) for row in rows]
    trade_numbers = [int(row["trade_id"]) for row in rows]

    if output_path is None:
        output_path = csv_path.with_name("equity_curve_dual_axis.png")

    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.plot(times, balances, color="#1f77b4", linewidth=1.0, marker="o", markersize=2.2)
    ax.set_title(f"Equity Curve - Time and Trade Count - {csv_path.stem}")
    ax.set_xlabel("Closed Time (Beijing)")
    ax.set_ylabel("Balance (USDT)")
    ax.grid(True, alpha=0.28)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=BEIJING_TZ))
    fig.autofmt_xdate()

    ax_top = ax.twiny()
    ax_top.set_xlim(ax.get_xlim())

    tick_count = min(10, len(times))
    step = max(1, len(times) // tick_count)
    tick_indexes = list(range(0, len(times), step))
    if tick_indexes[-1] != len(times) - 1:
        tick_indexes.append(len(times) - 1)

    tick_positions = [times[index] for index in tick_indexes]
    top_labels = [str(trade_numbers[index]) for index in tick_indexes]

    ax_top.set_xticks(tick_positions)
    ax_top.set_xticklabels(top_labels)
    ax_top.set_xlabel("Trade Number")

    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close(fig)

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw an equity curve from trades.csv")
    parser.add_argument("csv_path", nargs="?", default="reports/run_20260504_161519_utc/trades.csv")
    parser.add_argument(
        "--mode",
        choices=("trade", "time", "both"),
        default="both",
        help="Plot by closed trade number, by UTC time, or with both axes",
    )
    parser.add_argument("-o", "--output", help="Output PNG path")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    output_path = Path(args.output) if args.output else None
    if args.mode == "time":
        png_path = build_time_equity_curve(csv_path, output_path)
    elif args.mode == "both":
        png_path = build_dual_axis_curve(csv_path, output_path)
    else:
        png_path = build_equity_curve(csv_path, output_path)
    print(png_path)


if __name__ == "__main__":
    main()