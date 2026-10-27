"""
mock_client.py - Emulatore offline di Garmin Connect per collaudo locale.

Carica i dati telemetrici da mock_data/running_activity.json e simula
i metodi dell'interfaccia garminconnect.Garmin usati in src/telemetry.py.
"""

import json
from pathlib import Path


class MockGarminClient:
    """Client simulato per sviluppo e test offline a costo zero."""

    def __init__(self, mock_file_path: Path | str | None = None):
        if mock_file_path is None:
            project_root = Path(__file__).resolve().parent.parent
            mock_file_path = project_root / "mock_data" / "running_activity.json"

        self.mock_file = Path(mock_file_path)
        if not self.mock_file.exists():
            raise FileNotFoundError(f"File mock non trovato: {self.mock_file}")

        with open(self.mock_file, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def get_activities(self, start: int = 0, limit: int = 5) -> list[dict]:
        """Restituisce la lista di attività simulate."""
        activity = self._data.get("activity", {})
        return [activity] if activity else []

    def get_activity_weather(self, act_id: int | str) -> dict:
        """Restituisce i dati meteo simulati."""
        return self._data.get("weather", {})

    def get_activity_hr_in_timezones(self, act_id: int | str) -> list[dict]:
        """Restituisce le percentuali nelle zone cardio simulate."""
        return self._data.get("hr_zones", [])

    def get_activity_splits(self, act_id: int | str) -> dict:
        """Restituisce i lap / split intermedi simulati."""
        return self._data.get("splits", {})
