#!/usr/bin/env python3
"""
PnL Attribution CSV Exporter - Daily Historical Snapshots

Exports comprehensive model performance data to CSV files for analysis,
reporting, and compliance requirements.

Usage:
    python ops/export_pnl.py
        OR
    python -m ops.export_pnl

Output: ops/exports/pnl_YYYY-MM-DD.csv
"""
import os
import csv
from pathlib import Path
from datetime import datetime
import asyncio
from ops.net import create_async_client, request_with_retry


EXPORTS_DIR = Path("ops/exports")
EXPORTS_DIR.mkdir(exist_ok=True)


def format_currency(value):
    """Format numeric values as currency strings."""
    try:
        num = float(value) if value is not None else 0.0
        return f"${num:,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def format_percentage(value):
    """Format numeric values as percentage strings."""
    try:
        num = float(value) if value is not None else 0.0
        return f"{num:.2f}%"
    except (TypeError, ValueError):
        return "0.00%"


def format_number(value):
    """Format numeric values with appropriate precision."""
    try:
        num = float(value) if value is not None else 0.0
        return f"{num:.2f}"
    except (TypeError, ValueError):
        return "0.00"


async def fetch_pnl_data(ops_url="http://localhost:8002"):
    """
    Fetch comprehensive PnL data from the OPS API.

    Args:
        ops_url: Base URL of OPS API

    Returns:
        Dict containing timestamp and models data, or None if failed
    """
    try:
        async with create_async_client() as client:
            response = await request_with_retry(
                client, "GET", f"{ops_url}/dash/pnl", retries=2, backoff_base=0.5
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:  # noqa: BLE001
        print(f"Failed to fetch PnL data: {e}")
        return None


def prepare_model_row(model_data, portfolio_summary, export_timestamp):
    """
    Prepare a single model's data for CSV export.

    Args:
        model_data: Individual model performance data
        portfolio_summary: Overall portfolio summary
        export_timestamp: When the export was generated

    Returns:
        Dict ready for CSV row
    """
    return {
        # Metadata
        "export_timestamp": export_timestamp,
        "export_date": export_timestamp.split()[0],
        "export_time": export_timestamp.split()[1] if " " in export_timestamp else "",
        # Model identification
        "model": model_data.get("model", "unknown"),
        "venue": model_data.get("venue", "unknown"),
        "strategy_type": model_data.get("strategy_type", ""),
        "version": model_data.get("version", ""),
        "created_at": model_data.get("created_at", ""),
        # Core P&L metrics
        "realized_pnl": model_data.get("pnl_realized_total", 0.0),
        "unrealized_pnl": model_data.get("pnl_unrealized_total", 0.0),
        "total_pnl": model_data.get("total_pnl", 0.0),
        "total_pnl_pct": model_data.get("return_pct", 0.0),
        # Trading metrics
        "orders_filled": model_data.get("orders_filled_total", 0),
        "orders_submitted": model_data.get("orders_submitted_total", 0),
        "win_rate": model_data.get("win_rate", 0.0),
        "trades": model_data.get("trades", 0),
        # Risk metrics
        "sharpe_ratio": model_data.get("sharpe", 0.0),
        "max_drawdown": model_data.get("drawdown", 0.0),
        "avg_win": model_data.get("avg_win", 0.0),
        "avg_loss": model_data.get("avg_loss", 0.0),
        "trading_days": model_data.get("trading_days", 0),
        # Portfolio context
        "portfolio_total_realized": portfolio_summary.get("total_realized_pnl", 0.0),
        "portfolio_total_unrealized": portfolio_summary.get("total_unrealized_pnl", 0.0),
        "portfolio_total_trades": portfolio_summary.get("total_trades", 0),
        "portfolio_sharpe": portfolio_summary.get("sharpe_portfolio", 0.0),
        "portfolio_max_drawdown": portfolio_summary.get("max_drawdown_portfolio", 0.0),
        # Attribution (% of portfolio this model represents)
        "pnl_attribution_pct": (
            (model_data.get("total_pnl", 0.0) / max(portfolio_summary.get("total_pnl", 1), 0.01))
            * 100
            if portfolio_summary.get("total_pnl", 0) != 0
            else 0.0
        ),
        # Data quality flags
        "data_quality_score": 1.0,  # Placeholder - could implement data quality checks
        "metrics_source": "prometheus",
        "export_version": "1.0",
    }


def export_to_csv(models_data, portfolio_summary, timestamp=None):
    """
    Export PnL data to CSV file.

    Args:
        models_data: List of model performance data
        portfolio_summary: Overall portfolio summary
        timestamp: Export timestamp, defaults to current time

    Returns:
        Path to the exported file, or None if failed
    """
    if timestamp is None:
        timestamp = datetime.now()

    timestamp.strftime("%Y-%m-%d_%H-%M-%S")
    export_date = timestamp.strftime("%Y-%m-%d")
    export_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")

    # Prepare filename
    basename = f"pnl_{export_date}"
    filename = EXPORTS_DIR / f"{basename}.csv"
    counter = 1

    # Handle multiple exports per day
    while filename.exists():
        filename = EXPORTS_DIR / f"{basename}_{counter}.csv"
        counter += 1

    try:
        # Prepare CSV data
        csv_rows = []

        for model in models_data:
            row = prepare_model_row(model, portfolio_summary, export_timestamp)
            csv_rows.append(row)

        if not csv_rows:
            print("No data to export")
            return None

        # Define CSV columns (comprehensive field set)
        fieldnames = [
            # Metadata
            "export_timestamp",
            "export_date",
            "export_time",
            # Model identification
            "model",
            "venue",
            "strategy_type",
            "version",
            "created_at",
            # Core P&L metrics
            "realized_pnl",
            "unrealized_pnl",
            "total_pnl",
            "total_pnl_pct",
            # Trading metrics
            "orders_filled",
            "orders_submitted",
            "win_rate",
            "trades",
            # Risk metrics
            "sharpe_ratio",
            "max_drawdown",
            "avg_win",
            "avg_loss",
            "trading_days",
            # Portfolio context
            "portfolio_total_realized",
            "portfolio_total_unrealized",
            "portfolio_total_trades",
            "portfolio_sharpe",
            "portfolio_max_drawdown",
            # Attribution
            "pnl_attribution_pct",
            # Data quality
            "data_quality_score",
            "metrics_source",
            "export_version",
        ]

        # Write CSV file
        with open(filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)

        # Create summary file
        summary_filename = filename.with_suffix(".summary.txt")
        with open(summary_filename, "w", encoding="utf-8") as summary_file:
            summary_file.write(f"PnL Attribution Export Summary\n")
            summary_file.write(f"================================\n\n")
            summary_file.write(f"Export Date: {export_timestamp}\n")
            summary_file.write(f"Export File: {filename.name}\n\n")

            summary_file.write(f"Portfolio Summary:\n")
            summary_file.write(
                f"- Total Realized P&L: {format_currency(portfolio_summary.get('total_realized_pnl', 0))}\n"
            )
            summary_file.write(
                f"- Total Unrealized P&L: {format_currency(portfolio_summary.get('total_unrealized_pnl', 0))}\n"
            )
            summary_file.write(f"- Total Trades: {portfolio_summary.get('total_trades', 0)}\n")
            summary_file.write(
                f"- Portfolio Sharpe: {portfolio_summary.get('sharpe_portfolio', 0):.2f}\n\n"
            )

            summary_file.write(f"Models Exported: {len(csv_rows)}\n")

            # Group by model for summary
            model_totals = {}
            for row in csv_rows:
                model = row["model"]
                if model not in model_totals:
                    model_totals[model] = {
                        "realized": 0,
                        "unrealized": 0,
                        "trades": 0,
                        "venues": set(),
                    }
                model_totals[model]["realized"] += row["realized_pnl"]
                model_totals[model]["unrealized"] += row["unrealized_pnl"]
                model_totals[model]["trades"] += row["orders_filled"]
                model_totals[model]["venues"].add(row["venue"])

            summary_file.write("\nModel Performance Summary:\n")
            for model, totals in model_totals.items():
                total_pnl = totals["realized"] + totals["unrealized"]
                summary_file.write(
                    f"- {model}: {format_currency(total_pnl)} "
                    f"({totals['trades']} trades, {len(totals['venues'])} venues)\n"
                )

        print(f"✅ PnL data exported to: {filename}")
        print(f"📄 Summary: {summary_filename}")

        return filename

    except Exception as e:
        print(f"Failed to export CSV: {e}")
        return None


async def export_daily_pnl_snapshot(ops_url="http://localhost:8002"):
    """
    Export a complete daily PnL snapshot.

    Args:
        ops_url: OPS API base URL

    Returns:
        Path to exported file if successful, None otherwise
    """
    print("🔄 Fetching PnL data from OPS API...")

    # Fetch data
    data = await fetch_pnl_data(ops_url)

    if not data:
        print("❌ Failed to fetch PnL data")
        return None

    if "models" not in data:
        print("❌ No model data in response")
        return None

    models = data.get("models", [])
    portfolio_summary = data.get("portfolio_summary", {})
    timestamp = datetime.now()

    print(f"📊 Exporting {len(models)} model entries...")
    print(
        f"💰 Portfolio Realized: {format_currency(portfolio_summary.get('total_realized_pnl', 0))}"
    )
    print(
        f"📈 Portfolio Unrealized: {format_currency(portfolio_summary.get('total_unrealized_pnl', 0))}"
    )

    # Export to CSV
    result_file = export_to_csv(models, portfolio_summary, timestamp)

    if result_file:
        # Create a symlink to latest export for convenience
        latest_link = EXPORTS_DIR / "pnl_latest.csv"
        try:
            if latest_link.exists():
                latest_link.unlink()
            latest_link.symlink_to(result_file.name)
        except (OSError, NotImplementedError):
            # Symlinks not supported on all platforms, skip silently
            pass

    return result_file


async def main():
    """
    Main execution function.

    Can be called directly or as a cron job.
    """
    print("🗂️ PnL Attribution CSV Exporter")
    print("=" * 40)

    # Allow override of OPS URL via environment
    ops_url = os.getenv("OPS_URL", "http://localhost:8002")

    result_file = await export_daily_pnl_snapshot(ops_url)

    if result_file:
        print("\n✅ Export completed successfully!")
        print(f"📁 File location: {result_file}")
        print(f"💾 Total size: {result_file.stat().st_size} bytes")
    else:
        print("\n❌ Export failed!")
        return False

    return True


if __name__ == "__main__":
    # Run export when called directly
    success = asyncio.run(main())
    exit(0 if success else 1)
