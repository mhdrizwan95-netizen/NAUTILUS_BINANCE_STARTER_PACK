from __future__ import annotations

"""
On-chain DEX executor built on UniswapV2/Pancake router.
"""

from dataclasses import dataclass
import logging
from typing import Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.dex.wallet import DexWallet
    from engine.dex.router import DexRouter


logger = logging.getLogger("engine.dex.executor")


@dataclass(slots=True)
class DexExecutionResult:
    symbol: str
    qty: float
    price: float
    notional: float
    side: str
    tx_hash: Optional[str] = None


class DexExecutor:
    def __init__(
        self,
        *,
        wallet: "DexWallet",
        router: "DexRouter",
        stable_token: str,
        wrapped_native: str,
        gas_limit: int,
        slippage_bps: float,
    ) -> None:
        self.wallet = wallet
        self.router = router
        self.stable_token = stable_token
        self.wrapped_native = wrapped_native
        self.gas_limit = gas_limit
        self.slippage_bps = slippage_bps

    async def buy(
        self,
        *,
        symbol: str,
        token_address: str,
        notional_usd: float,
    ) -> DexExecutionResult:
        decimals_in = await self.wallet.token_decimals(self.stable_token)
        decimals_out = await self.wallet.token_decimals(token_address)
        amount_in = int(notional_usd * (10**decimals_in))
        if amount_in <= 0:
            raise ValueError("Amount in must be positive")
        path = self._path_buy(token_address)
        await self.wallet.ensure_allowance(
            self.stable_token, self.router.router.address, amount_in
        )
        quote = await self.router.quote(amount_in, path)
        min_out = int(quote.amount_out * (1 - self.slippage_bps / 10_000))
        gas_price = min(self.wallet.w3.eth.gas_price, self.wallet.max_gas_price_wei)
        tx = self.router.build_swap_tx(
            amount_in=amount_in,
            amount_out_min=min_out,
            path=path,
            to=self.wallet.address,
            gas_limit=self.gas_limit,
            gas_price=gas_price,
        )
        receipt = await self.wallet.send_transaction(tx)
        qty = quote.amount_out / (10**decimals_out)
        px = (amount_in / (10**decimals_in)) / max(qty, 1e-12)
        return DexExecutionResult(
            symbol=symbol,
            qty=qty,
            price=px,
            notional=notional_usd,
            side="BUY",
            tx_hash=receipt.transactionHash.hex(),
        )

    async def sell(
        self,
        *,
        symbol: str,
        token_address: str,
        qty: float,
    ) -> DexExecutionResult:
        decimals_in = await self.wallet.token_decimals(token_address)
        decimals_out = await self.wallet.token_decimals(self.stable_token)
        amount_in = int(qty * (10**decimals_in))
        if amount_in <= 0:
            raise ValueError("Sell quantity must be positive")
        path = self._path_sell(token_address)
        await self.wallet.ensure_allowance(
            token_address, self.router.router.address, amount_in
        )
        quote = await self.router.quote(amount_in, path)
        min_out = int(quote.amount_out * (1 - self.slippage_bps / 10_000))
        gas_price = min(self.wallet.w3.eth.gas_price, self.wallet.max_gas_price_wei)
        tx = self.router.build_swap_tx(
            amount_in=amount_in,
            amount_out_min=min_out,
            path=path,
            to=self.wallet.address,
            gas_limit=self.gas_limit,
            gas_price=gas_price,
        )
        receipt = await self.wallet.send_transaction(tx)
        stable_amount = quote.amount_out / (10**decimals_out)
        px = stable_amount / max(qty, 1e-12)
        return DexExecutionResult(
            symbol=symbol,
            qty=qty,
            price=px,
            notional=stable_amount,
            side="SELL",
            tx_hash=receipt.transactionHash.hex(),
        )

    def _path_buy(self, token_address: str) -> Sequence[str]:
        token_cs = self.wallet.w3.to_checksum_address(token_address)
        stable_cs = self.wallet.w3.to_checksum_address(self.stable_token)
        if self.wrapped_native and self.wrapped_native.lower() not in {
            stable_cs.lower(),
            token_cs.lower(),
        }:
            return (
                stable_cs,
                self.wallet.w3.to_checksum_address(self.wrapped_native),
                token_cs,
            )
        return (stable_cs, token_cs)

    def _path_sell(self, token_address: str) -> Sequence[str]:
        token_cs = self.wallet.w3.to_checksum_address(token_address)
        stable_cs = self.wallet.w3.to_checksum_address(self.stable_token)
        if self.wrapped_native and self.wrapped_native.lower() not in {
            stable_cs.lower(),
            token_cs.lower(),
        }:
            return (
                token_cs,
                self.wallet.w3.to_checksum_address(self.wrapped_native),
                stable_cs,
            )
        return (token_cs, stable_cs)
