"""
Interactive Brokers configuration for Nautilus adapter.
"""
from dataclasses import dataclass
from typing import Optional
import os


@dataclass
class IBKRConfig:
    """IBKR connection configuration."""

    host: str = "127.0.0.1"
    port: int = 7497  # 7496 for TWS, 4002 for IB Gateway
    client_id: int = 101
    paper: bool = True
    account: Optional[str] = None
    timeout: int = 30
    readonly: bool = False

    @classmethod
    def from_env(cls) -> "IBKRConfig":
        """Create config from environment variables."""
        return cls(
            host=os.getenv("IBKR_HOST", "127.0.0.1"),
            port=int(os.getenv("IBKR_PORT", "7497")),
            client_id=int(os.getenv("IBKR_CLIENT_ID", "101")),
            paper=os.getenv("IBKR_MODE", "paper").lower() == "paper",
            account=os.getenv("IBKR_ACCOUNT"),
            timeout=int(os.getenv("IBKR_TIMEOUT", "30")),
            readonly=os.getenv("IBKR_READONLY", "false").lower() == "true",
        )

    @property
    def gateway_port(self) -> int:
        """Return appropriate port for gateway vs TWS."""
        return 4002 if not self.paper else 4001

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        return {
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "paper": self.paper,
            "account": self.account,
            "timeout": self.timeout,
            "readonly": self.readonly,
        }
