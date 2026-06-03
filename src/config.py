"""
Configuration module — loads and validates environment variables.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Binance API
    binance_api_key: str
    binance_api_secret: str
    binance_api_base: str = "https://testnet.binancefuture.com"
    binance_ws_base: str = "wss://stream.binancefuture.com"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: int = 0

    # Symbols (comma-separated in env, parsed to list)
    symbols: str = "BTCUSDT"

    # Risk parameters
    margin_cap: float = 1000.0
    leverage: int = 100
    sl_delta: float = 0.0015

    # Institutional filter thresholds
    long_retail_ls_max: float = 1.0
    long_top_ls_min: float = 1.5
    short_retail_ls_min: float = 1.5
    short_top_ls_max: float = 0.8

    # Post-trade cooldown (number of 5m candles)
    post_trade_cooldown: int = 3

    # API weight safety
    api_weight_pause_threshold: int = 1800

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.symbols.split(",") if s.strip()]

    @property
    def is_testnet(self) -> bool:
        return "testnet" in self.binance_api_base.lower()


def load_settings(env_file: str = ".env") -> Settings:
    """Load settings from a specific env file."""
    return Settings(_env_file=env_file)
