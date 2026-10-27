"""
rate_limiter.py - Gestione dinamica del rate-limit per Google Gemini Free Tier.

Implementa un rate limiter asincrono con finestra scorrevole a 60 secondi
per evitare l'errore 429 Too Many Requests (limite Free Tier: 15 RPM).
"""

import asyncio
import time
from collections import deque


class GeminiRateLimiter:
    """Sliding-window rate limiter per chiamate API Gemini."""

    def __init__(self, max_rpm: int = 12, min_interval_seconds: float = 2.0):
        """
        :param max_rpm: Numero massimo di richieste consentite per minuto (default 12 per sicurezza rispetto a 15)
        :param min_interval_seconds: Intervallo minimo garantito tra due chiamate consecutive
        """
        self.max_rpm = max_rpm
        self.min_interval = min_interval_seconds
        self.timestamps: deque[float] = deque()
        self.last_call_time: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self, agent_name: str = ""):
        """Attende se necessario prima di consentire la richiesta all'API."""
        async with self._lock:
            now = time.monotonic()

            # Pulisce i timestamp più vecchi di 60 secondi
            while self.timestamps and now - self.timestamps[0] >= 60.0:
                self.timestamps.popleft()

            # Controllo 1: Quota al minuto raggiunta
            if len(self.timestamps) >= self.max_rpm:
                oldest = self.timestamps[0]
                wait_time = max(0.1, 60.0 - (now - oldest) + 0.5)
                tag = f"[{agent_name}] " if agent_name else ""
                print(
                    f"⏳ {tag}Rate-limit Gemini Free Tier: raggiunte {len(self.timestamps)}/{self.max_rpm} RPM. "
                    f"Pausa di sicurezza di {wait_time:.1f}s..."
                )
                await asyncio.sleep(wait_time)
                now = time.monotonic()
                while self.timestamps and now - self.timestamps[0] >= 60.0:
                    self.timestamps.popleft()

            # Controllo 2: Intervallo minimo tra chiamate consecutive (anti-burst)
            elapsed_since_last = now - self.last_call_time
            if elapsed_since_last < self.min_interval:
                sleep_needed = self.min_interval - elapsed_since_last
                await asyncio.sleep(sleep_needed)
                now = time.monotonic()

            # Registra la chiamata corrente
            self.timestamps.append(now)
            self.last_call_time = now


# Istanza singleton globale per l'applicazione
global_rate_limiter = GeminiRateLimiter(max_rpm=12, min_interval_seconds=2.0)
