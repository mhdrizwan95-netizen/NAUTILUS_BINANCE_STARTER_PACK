from __future__ import annotations

"""
Wallet utilities for on-chain DEX execution.

This module wraps Web3 interactions so the rest of the strategy can remain
async-friendly while underlying RPC calls run in a thread pool.
"""

from dataclasses import dataclass
import asyncio
import functools
import logging
from typing import Dict

from web3 import Web3
from web3.contract import Contract
from web3.types import TxParams, TxReceipt

ERC20_ABI = [
    {
        "name": "decimals",
        "outputs": [{"type": "uint8"}],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "balanceOf",
        "outputs": [{"type": "uint256"}],
        "inputs": [{"name": "owner", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "allowance",
        "outputs": [{"type": "uint256"}],
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "approve",
        "outputs": [{"type": "bool"}],
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

MAX_ALLOWANCE = 2**256 - 1


logger = logging.getLogger("engine.dex.wallet")


@dataclass(slots=True)
class TokenInfo:
    address: str
    decimals: int


class DexWallet:
    def __init__(
        self,
        *,
        rpc_url: str,
        chain_id: int,
        private_key: str,
        max_gas_price_wei: int,
    ) -> None:
        if not rpc_url:
            raise ValueError("DEX_RPC_URL missing")
        if not private_key:
            raise ValueError("DEX_PRIVATE_KEY missing")
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        if not self.w3.is_connected():
            raise RuntimeError(f"Failed to connect to RPC {rpc_url}")
        self.chain_id = chain_id
        self._acct = self.w3.eth.account.from_key(private_key)
        self.address = self._acct.address
        self.max_gas_price_wei = max_gas_price_wei
        self._token_cache: Dict[str, TokenInfo] = {}
        self._lock = asyncio.Lock()
        logger.info(
            "[DEX] wallet online address=%s chain_id=%s", self.address, chain_id
        )

    def _erc20(self, token: str) -> Contract:
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(token), abi=ERC20_ABI
        )

    async def token_decimals(self, token: str) -> int:
        token_up = token.lower()
        if token_up in self._token_cache:
            return self._token_cache[token_up].decimals
        decimals = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: self._erc20(token).functions.decimals().call(),
        )
        self._token_cache[token_up] = TokenInfo(address=token, decimals=int(decimals))
        return int(decimals)

    async def allowance(self, token: str, spender: str) -> int:
        return await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: self._erc20(token)
            .functions.allowance(self.address, Web3.to_checksum_address(spender))
            .call(),
        )

    async def ensure_allowance(self, token: str, spender: str, amount: int) -> None:
        current = await self.allowance(token, spender)
        if current >= amount:
            return
        logger.info(
            "[DEX] approving %s for %s (current=%s target=%s)",
            token,
            spender,
            current,
            amount,
        )
        contract = self._erc20(token)
        tx = contract.functions.approve(
            Web3.to_checksum_address(spender), MAX_ALLOWANCE
        ).build_transaction(
            {
                "from": self.address,
                "chainId": self.chain_id,
                "nonce": self.w3.eth.get_transaction_count(self.address),
                "gasPrice": min(self.w3.eth.gas_price, self.max_gas_price_wei),
            }
        )
        tx.setdefault("gas", 80_000)
        await self.send_transaction(tx)

    async def send_transaction(self, tx: TxParams) -> TxReceipt:
        async with self._lock:
            tx["nonce"] = tx.get(
                "nonce", self.w3.eth.get_transaction_count(self.address)
            )
            tx["chainId"] = tx.get("chainId", self.chain_id)
            if "gasPrice" not in tx:
                tx["gasPrice"] = min(self.w3.eth.gas_price, self.max_gas_price_wei)
            signed = self._acct.sign_transaction(tx)
            tx_hash = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.w3.eth.send_raw_transaction(signed.rawTransaction)
            )
        logger.info("[DEX] broadcast tx=%s", tx_hash.hex())
        receipt = await asyncio.get_running_loop().run_in_executor(
            None,
            functools.partial(
                self.w3.eth.wait_for_transaction_receipt, tx_hash, timeout=180
            ),
        )
        if receipt.status != 1:
            raise RuntimeError(f"Transaction reverted: {tx_hash.hex()}")
        return receipt

    async def balance_of(self, token: str) -> int:
        return await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: self._erc20(token).functions.balanceOf(self.address).call(),
        )
