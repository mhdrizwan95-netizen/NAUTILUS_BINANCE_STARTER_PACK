# ops/strategy_ui.py
import json
from pathlib import Path

_JSON_ERRORS = (OSError, json.JSONDecodeError)


def generate_html_table(registry_path: Path) -> str:
    """Generate HTML table rows from strategy registry."""
    try:
        registry = json.loads(registry_path.read_text())

        rows = []
        current_model = registry.get("current_model")

        # Get all models (excluding metadata keys)
        models = [
            (k, v)
            for k, v in registry.items()
            if k not in ("current_model", "promotion_log") and isinstance(v, dict)
        ]

        # Sort models by Sharpe ratio descending (same as governance ranking)
        models.sort(key=lambda kv: kv[1].get("sharpe", 0), reverse=True)

        for model_name, stats in models:
            # Format for display
            version = stats.get("version", "—")
            sharpe = f"{stats.get('sharpe', 0):.2f}" if stats.get("sharpe", 0) != 0 else "—"
            drawdown = f"{stats.get('drawdown', 0):.2f}" if stats.get("drawdown", 0) != 0 else "—"
            realized = f"{stats.get('realized', 0):.2f}" if stats.get("realized", 0) != 0 else "—"

            trades = stats.get("trades", 0)
            last_promotion = stats.get("last_promotion", "") or "—"

            # Mark current model
            css_class = "current-row" if model_name == current_model else ""

            # Format last promotion timestamp
            if last_promotion != "—":
                try:
                    # Truncate to just date/time for display
                    last_promotion = last_promotion[:16].replace("T", " ")
                except (TypeError, AttributeError):
                    pass

            row = f'<tr class="{css_class}"><td>{model_name}</td><td>{version}</td><td class="sharpe">{sharpe}</td><td>{drawdown}</td><td class="positive">{realized}</td><td>{trades}</td><td>{last_promotion}</td></tr>'
            rows.append(row)

        return "\n".join(rows)

    except _JSON_ERRORS as exc:
        return (
            "<tr><td colspan='7' style='color: red;'>Error loading registry: "
            f"{str(exc)[:50]}</td></tr>"
        )


def get_strategy_ui_html() -> str:
    """Return the complete HTML dashboard page."""
    registry_path = Path("ops/strategy_registry.json")

    try:
        table_rows = generate_html_table(registry_path)
    except _JSON_ERRORS as exc:
        table_rows = (
            f"<tr><td colspan='7' style='color: red;'>Critical error: {str(exc)[:100]}</td></tr>"
        )
    current_model = "Unknown"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text())
            current_model = registry.get("current_model", current_model)
        except _JSON_ERRORS:
            pass

    # Professional dark theme HTML dashboard
    html = """<html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Strategy Governance Dashboard</title>
        <style>
            /* Professional dark theme inspired by institutional trading desks */
            body {
                margin: 0;
                padding: 20px;
                background: linear-gradient(135deg, #0f1419 0%, #1a1d29 100%);
                color: #e2e8f0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                min-height: 100vh;
            }

            .container {
                max-width: 1400px;
                margin: 0 auto;
                background: rgba(15, 23, 41, 0.95);
                border-radius: 12px;
                padding: 30px;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
            }

            h1 {
                color: #00d4aa;
                margin-bottom: 10px;
                font-size: 2.5em;
                font-weight: 600;
                text-align: center;
                text-shadow: 0 2px 4px rgba(0, 212, 170, 0.2);
            }

            .subtitle {
                color: #64748b;
                text-align: center;
                margin-bottom: 30px;
                font-size: 1.1em;
            }

            .status-bar {
                background: linear-gradient(90deg, #1a365d 0%, #2d3748 100%);
                padding: 15px 20px;
                border-radius: 8px;
                margin-bottom: 25px;
                border-left: 4px solid #00d4aa;
            }

            .status-bar h3 {
                color: #00d4aa;
                margin: 0 0 8px 0;
                font-size: 1.2em;
            }

            .current-model {
                color: #fbbf24;
                font-weight: bold;
                font-size: 1.1em;
            }

            table {
                width: 100%;
                border-collapse: collapse;
                background: rgba(30, 41, 59, 0.8);
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
            }

            th {
                background: linear-gradient(90deg, #374151 0%, #1f2937 100%);
                color: #f3f4f6;
                padding: 15px;
                text-align: left;
                font-weight: 600;
                text-transform: uppercase;
                font-size: 0.85em;
                letter-spacing: 0.5px;
                border-bottom: 2px solid #00d4aa;
            }

            td {
                padding: 15px;
                border-bottom: 1px solid rgba(75, 85, 99, 0.3);
                transition: background-color 0.2s ease;
            }

            tr:hover td {
                background: rgba(59, 130, 246, 0.1);
            }

            .current-row {
                background: rgba(34, 197, 94, 0.1) !important;
            }

            .current-row td {
                font-weight: 600;
                color: #68d391;
            }

            .sharpe {
                font-weight: 500;
            }

            .positive { color: #10b981; }
            .negative { color: #ef4444; }
            .neutral { color: #6b7280; }

            .performance-bar {
                background: rgba(255, 255, 255, 0.1);
                border-radius: 3px;
                height: 6px;
                margin-top: 4px;
            }

            .performance-fill {
                background: linear-gradient(90deg, #ef4444 0%, #fbbf24 50%, #10b981 100%);
                border-radius: 3px;
                height: 100%;
                transition: width 0.3s ease;
            }

            .footer {
                margin-top: 40px;
                text-align: center;
                color: #6b7280;
                font-size: 0.9em;
            }

            .refresh-notice {
                margin-top: 15px;
                font-size: 0.85em;
                color: #9ca3af;
            }

            /* Responsive design */
            @media (max-width: 768px) {
                .container {
                    padding: 20px;
                }
                th, td {
                    padding: 10px 8px;
                }
                h1 {
                    font-size: 2em;
                }
            }
        </style>
        <meta http-equiv="refresh" content="30"> <!-- Auto-refresh every 30 seconds -->
    </head>
    <body>
        <div class="container">
            <h1>🧠 Strategy Governance Dashboard</h1>
            <div class="subtitle">Autonomous Model Performance Oversight & Promotion Control</div>

            <div class="status-bar">
                <h3>🚀 Live Control</h3>
                <div class="current-model">Current Active Strategy: {current_model}</div>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Strategy Model</th>
                        <th>Version</th>
                        <th>Sharpe Ratio</th>
                        <th>Max Drawdown</th>
                        <th>Realized P&L</th>
                        <th>Total Trades</th>
                        <th>Last Promotion</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>

            <div class="footer">
                <div>⚡ Dashboard auto-refreshes every 30 seconds • Data updates live from OPS telemetry</div>
                <div>🎯 Models are automatically promoted based on Sharpe ratio optimization with drawdown penalties</div>
            </div>
        </div>
    </body>
    </html>
    """

    return html.replace("{current_model}", current_model).replace("{table_rows}", table_rows)
