# Production Deployment Guide

This guide describes how to deploy the Nautilus HMM Starter Pack to a production environment.

## Prerequisites

- Docker Engine 24+ & Docker Compose v2
- Python 3.11+ (for local scripts)
- Binance API Credentials (Futures & Spot)
- A secure server (e.g., AWS EC2, DigitalOcean Droplet) with at least 4GB RAM.

## 1. Environment Setup

1.  **Clone the Repository**:
    ```bash
    git clone <repo-url>
    cd NAUTILUS_BINANCE_STARTER_PACK
    ```

2.  **Configure Secrets**:
    Copy the example environment file and populate it with your production credentials.
    ```bash
    cp env.example .env
    nano .env
    ```
    **Critical Variables**:
    - `BINANCE_API_KEY`, `BINANCE_API_SECRET`: Your trading keys.
    - `OPS_API_TOKEN`: A strong, random string for securing the Ops API and WebSocket.
    - `TRADING_ENABLED`: Set to `true` for live trading (default `false`).
    - `BINANCE_MODE`: Set to `live` (default `demo`).

3.  **Network Setup**:
    Ensure the Docker network exists.
    ```bash
    docker network create nautilus_trading_network || true
    ```

## 2. Build and Launch

1.  **Build Images**:
    ```bash
    make build
    ```

2.  **Start Core Services**:
    ```bash
    make up-core
    ```
    This starts:
    - `engine_binance` (Port 8003): Trading Engine & WebSocket Telemetry.
    - `ops` (Port 8002): Command Center API & Static Assets.
    - `universe`, `situations`, `screener`: Support services.

3.  **Start Observability (Optional but Recommended)**:
    ```bash
    make up-obs
    ```
    This starts Prometheus (9090) and Grafana (3000).

## 3. Verification

1.  **Check Health**:
    ```bash
    curl -f http://localhost:8003/health
    curl -f http://localhost:8002/health
    ```

2.  **Access Command Center**:
    Open `http://<server-ip>:8002` in your browser.
    - **Login**: Use the `OPS_API_TOKEN` you defined in `.env`.
    - **Verify Telemetry**: Check the "Glass Cockpit" dashboard. You should see real-time price ticks and order updates.
    - **Note**: The frontend connects to the WebSocket at `ws://<server-ip>:8003/ws`. Ensure port 8003 is accessible from your IP (configure firewall/security groups).

## 4. Maintenance

-   **Logs**:
    ```bash
    docker compose logs -f --tail=100 engine_binance
    ```
-   **Updates**:
    ```bash
    git pull
    make build
    make up-core
    ```
-   **Emergency Stop**:
    ```bash
    make down
    ```

## 5. Troubleshooting

-   **WebSocket Connection Failed**:
    -   Check if port 8003 is open on the firewall.
    -   Verify `OPS_API_TOKEN` matches between `.env` and the frontend.
    -   Check engine logs for `ConnectionManager` errors.

-   **No Market Data**:
    -   Verify Binance API keys are valid and have Futures permissions.
    -   Check `engine.log` for "BinanceUserStream" errors.
