from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

from arqen.tools.base import Tool


class WeatherForecastTool(Tool):
    name = "weather_forecast"
    description = "Returns a concise evening weather forecast for Gothenburg."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        params = urlencode({
            "latitude": 57.7089,
            "longitude": 11.9746,
            "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
            "forecast_days": 2,
            "timezone": "Europe/Stockholm",
        })
        request = Request(f"https://api.open-meteo.com/v1/forecast?{params}", headers={"User-Agent": "Arqen Desktop"})
        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        hourly = data["hourly"]
        now = datetime.now()
        candidates = []
        for index, stamp in enumerate(hourly["time"]):
            time = datetime.fromisoformat(stamp)
            if time.date() == now.date() and 18 <= time.hour <= 23:
                candidates.append(index)
        if not candidates:
            return "Jag hittade ingen timprognos för Göteborg i kväll."
        values = candidates
        temps = [hourly["temperature_2m"][i] for i in values]
        rain = max(hourly["precipitation_probability"][i] or 0 for i in values)
        wind = max(hourly["wind_speed_10m"][i] or 0 for i in values)
        codes = [hourly["weather_code"][i] for i in values]
        description = "klart eller delvis klart" if max(codes) <= 3 else "varierande väder"
        if any(code >= 51 for code in codes):
            description = "risk för regn"
        return (
            f"Göteborg i kväll: {description}. Temperatur cirka {min(temps):.0f}–{max(temps):.0f} °C, "
            f"regnrisk upp till {rain:.0f} % och vind upp till {wind:.0f} km/h. "
            "Källa: Open-Meteo."
        )
