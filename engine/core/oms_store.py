from typing import Iterator
from .oms_models import OrderRecord

class OMSStore:
    """
    In-memory Order Management System store.
    
    This is a temporary implementation to satisfy the Reconciliation Daemon dependencies.
    It tracks orders in memory and does not currently persist to SQLite, 
    though it is intended to wrap engine.storage.sqlite in the future.
    """
    def __init__(self):
        self._orders: dict[str, OrderRecord] = {}

    def list_open(self) -> Iterator[OrderRecord]:
        """Return iterator of all open orders."""
        return (
            o for o in self._orders.values() 
            if o.status in ("NEW", "PARTIALLY_FILLED", "ACCEPTED", "PENDING_NEW")
        )

    def upsert(self, record: OrderRecord, source: str) -> None:
        """Insert or update an order record."""
        self._orders[record.id] = record

    def close(self, order_id: str, status: str) -> None:
        """Mark an order as closed (FILLED/CANCELED/etc)."""
        if order_id in self._orders:
            self._orders[order_id].status = status

    def _persist(self) -> None:
        """Persist state to storage (No-op in-memory)."""
        pass
