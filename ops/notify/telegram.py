from __future__ import annotations

import aiohttp
import logging


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
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, timeout=10) as r:
                    if r.status != 200:
                        try:
                            body = await r.text()
                        except Exception:
                            body = "<no body>"
                        self.log.warning("[TG] send status %s: %s", r.status, body)
        except Exception as e:
            self.log.warning("[TG] send error: %s", e)

