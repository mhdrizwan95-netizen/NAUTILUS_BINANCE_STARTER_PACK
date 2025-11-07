from __future__ import annotations

"""
UniswapV2/PancakeSwap router helper.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import List, Sequence

from web3 import Web3

ROUTER_ABI = [
    {
        "name": "getAmountsOut",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path", "type": "address[]"},
        ],
        "outputs": [
            {"name": "amounts", "type": "uint256[]"},
        ],
    },
    {
        "name": "swapExactTokensForTokens",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"type": "uint256[]"}],
    },
]


@dataclass(slots=True)
class SwapQuote:
    amount_in: int
    amount_out: int
    path: List[str]


class DexRouter:
    def __init__(self, *, web3: Web3, router_address: str) -> None:
        if not router_address:
            raise ValueError("DEX_ROUTER_ADDRESS missing")
        self.w3 = web3
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(router_address),
            abi=ROUTER_ABI,
        )

    async def quote(self, amount_in: int, path: Sequence[str]) -> SwapQuote:
        path_cs = [Web3.to_checksum_address(p) for p in path]
        amount_out = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: self.router.functions.getAmountsOut(amount_in, path_cs).call(),
        )
        return SwapQuote(amount_in=amount_out[0], amount_out=amount_out[-1], path=path_cs)

    def build_swap_tx(
        self,
        *,
        amount_in: int,
        amount_out_min: int,
        path: Sequence[str],
        to: str,
        gas_limit: int,
        gas_price: int,
    ):
        deadline = int(time.time()) + 120  # two minutes
        path_cs = [Web3.to_checksum_address(p) for p in path]
        return self.router.functions.swapExactTokensForTokens(
            amount_in,
            amount_out_min,
            path_cs,
            Web3.to_checksum_address(to),
            deadline,
        ).build_transaction(
            {
                "from": Web3.to_checksum_address(to),
                "gas": gas_limit,
                "gasPrice": gas_price,
            }
        )
