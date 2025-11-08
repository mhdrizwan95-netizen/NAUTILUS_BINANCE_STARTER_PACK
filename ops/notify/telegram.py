from __future__ import annotations

import logging
import os
import socket

import aiohttp


class Telegram:
    def __init__(self, token: str, chat_id: str | int, log=None):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.log = log or logging.getLogger("ops.telegram")

    async def send(self, text: str, parse_mode: str = "Markdown") -> None:
        url = f"{self.base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        # Optional IPv4-only connector to avoid IPv6-only resolution in Docker
        force_ipv4 = os.getenv("TELEGRAM_FORCE_IPV4", "").lower() in {
            "1",
            "true",
            "yes",
        }
        connector = None
        try:
            if force_ipv4:
                connector = aiohttp.TCPConnector(family=socket.AF_INET)
        except Exception:
            connector = None
        try:
            async with aiohttp.ClientSession(connector=connector) as s:
                async with s.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        try:
                            body = await r.text()
                        except Exception:
                            body = "<no body>"
                        self.log.warning("[TG] send status %s: %s", r.status, body)
        except Exception as e:
            self.log.warning("[TG] send error: %s", e)
