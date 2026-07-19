"""Database models for asiabot based on state machine architecture."""

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class MarketStatus(enum.Enum):
    """Lifecycle status of a weather market."""

    OPEN = "open"
    BET_PLACED = "bet_placed"
    SETTLED_WIN = "settled_win"
    SETTLED_LOSS = "settled_loss"
    EXPIRED = "expired"
    ERROR = "error"


class BetStatus(enum.Enum):
    """Execution status of a bet."""

    PENDING = "pending"
    PLACED = "placed"
    ACTIVE = "active"
    OPEN = "open"
    CANCELLED = "cancelled"
    SETTLED = "settled"
    FAILED = "failed"
    WON = "won"
    LOST = "lost"


# â”€â”€ Open bet statuses â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# These status values all mean "bet is still active / not yet settled":
#   "active"  â€” being monitored by risk management
#   "open"    â€” initial state when a bet is created (default)
#   "placed"  â€” successfully submitted to exchange
#   "pending" â€” submitted but not yet confirmed
OPEN_BET_STATUSES = ("active", "open", "placed", "pending")


class WeatherMarket(Base):
    """Polymarket'ten Ã§ekilen aÃ§Ä±k hava betleri."""

    __tablename__ = "weather_markets"

    id = Column(String, primary_key=True)
    question = Column(String, nullable=False)

    # Parse edilmiÅŸ bilgiler
    city = Column(String)  # "New York"
    city_code = Column(String, default="")  # ICAO/city code
    metric = Column(String)  # "temperature_max"
    threshold = Column(Float)  # 95.0 (primary threshold, °C)
    threshold_unit = Column(String)  # "fahrenheit" or "celsius"
    threshold_low = Column(
        Float, nullable=True
    )  # range lower bound (°C), e.g. "88-89°F" ' 31.1
    threshold_high = Column(
        Float, nullable=True
    )  # range upper bound (°C), e.g. "88-89°F" ' 31.7
    target_date = Column(DateTime)  # 2025-07-04
    latitude = Column(Float)  # Latitude
    longitude = Column(Float)  # Longitude
    market_type = Column(String, nullable=True)  # "HIGH", "LOW", or "RANGE"

    # Polymarket fiyatlarÄ±
    yes_price = Column(Float)  # 0.35
    no_price = Column(Float)  # 0.65
    volume = Column(Float)  # $50,000
    liquidity = Column(Float)  # Liquidity

    # Durum
    status = Column(String, default=MarketStatus.OPEN.value)

    # Meta
    first_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_updated = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    raw_data = Column(Text)


class WeatherForecast(Base):
    """Meteoroloji API'lerinden Ã§ekilen tahminler."""

    __tablename__ = "weather_forecasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String)  # Hangi market iÃ§in

    # Konum
    city = Column(String)
    lat = Column(Float)
    lon = Column(Float)

    # Tahmin
    target_date = Column(DateTime)
    metric = Column(String)  # "temperature_max"

    # FarklÄ± kaynaklardan gelen deÄŸerler
    source = Column(String)  # "openmeteo", "weatherapi", "accuweather"
    predicted_value = Column(Float)  # 92.5
    confidence = Column(Float)  # Varsa

    model_weight = Column(Float, default=0.0)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    raw_data = Column(Text)


class Analysis(Base):
    """Analiz sonuÃ§larÄ±."""

    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String)

    # Hesaplanan deÄŸerler
    estimated_probability = Column(Float)  # 0.72 (gerÃ§ek olasÄ±lÄ±k tahmini)
    market_implied_prob = Column(Float)  # 0.35 (Polymarket'in fiyatÄ±)
    edge = Column(Float)  # 0.37 (fark) â€” now net edge after slippage+fee
    raw_edge = Column(Float, nullable=True)  # pre-cost raw edge
    slippage_pct = Column(Float, nullable=True)  # estimated slippage at fill

    # Kaynak detaylarÄ±
    avg_forecast_value = Column(Float)  # Ortalama tahmin: 92.5°F
    std_forecast_value = Column(Float)  # Standart sapma
    num_sources = Column(Integer)  # KaÃ§ kaynakta veri var

    # Karar
    recommended_side = Column(String)  # "YES" veya "NO"
    recommended_amount = Column(Float)  # Kelly criterion sonucu
    confidence_score = Column(Float)  # 0-1

    should_bet = Column(Boolean, default=False)  # Bet aÃ§Ä±lmalÄ± mÄ±?
    reason = Column(String)  # Neden evet/hayÄ±r

    # Per-model predictions for SIA weight optimization.
    # JSON: {"model_temps": {"gfs_seamless": 32.5, ...},
    #        "model_probs": {"gfs_seamless": 0.72, ...}}
    model_predictions = Column(Text, nullable=True)

    analyzed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Bet(Base):
    """AÃ§Ä±lan betler."""

    __tablename__ = "bets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String, nullable=False)
    analysis_id = Column(Integer)

    city_code = Column(String)
    city = Column(String)  # compatibility
    outcome = Column(String)  # "YES" or "NO"
    stake = Column(Float)  # DEPRECATED: dead column, kept for DB migration compatibility
    stake_amount = Column(Float, default=0.0)  # DEPRECATED: dead column, kept for DB migration compatibility
    entry_price = Column(Float)
    shares = Column(Float)
    current_price = Column(Float, default=0.5)
    pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    fair_value = Column(Float, default=0.0)
    expected_value = Column(Float, default=0.0)
    strike_temp = Column(Float)
    bet_type = Column(String)  # DEPRECATED: dead column, kept for DB migration compatibility
    side = Column(String)  # YES/NO/HIGH/LOW
    realized_pnl = Column(Float, default=0.0)
    status = Column(String, default=BetStatus.OPEN.value)
    ladder_data = Column(Text)  # JSON serialized
    result_data = Column(Text)  # JSON serialized

    # Blueprint Specific properties
    amount = Column(Float)  # $50
    price = Column(Float)  # 0.35
    potential_payout = Column(Float)  # $142.86
    order_id = Column(String)
    tx_hash = Column(String)
    error_message = Column(String)  # Hata varsa
    entry_fee = Column(
        Float, default=0.0
    )  # Polymarket taker fee at entry (feeRate Ã— stake Ã— (1-p))

    placed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    settled_at = Column(DateTime)
    close_reason = Column(String, nullable=True)
    closed_at = Column(DateTime, nullable=True)  # Early exit zamanÄ±

    # Partial take-profit state (principal recovery without full closure)
    partial_tp_done = Column(Boolean, default=False, nullable=False)
    covered_fraction = Column(Float, default=0.0, nullable=False)  # fraction sold on partial TP


class Portfolio(Base):
    """Portfolio state for tracking balances (integrated to match existing asiabot frontend)."""

    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True)
    initial_value = Column(Float, default=1000.0)
    current_value = Column(Float, default=1000.0)
    cash_balance = Column(Float, default=1000.0)
    total_value = Column(Float, default=1000.0)
    total_realized_pnl = Column(Float, default=0.0)
    total_won = Column(Integer, default=0)
    total_lost = Column(Integer, default=0)
    daily_pnl = Column(Float, default=0.0)
    last_updated = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ModelPerformance(Base):
    """Model performance tracking for SIA optimization."""

    __tablename__ = "model_performance"

    id = Column(Integer, primary_key=True)
    model_name = Column(String, nullable=False)
    total_predictions = Column(Integer, default=0)
    correct_predictions = Column(Integer, default=0)
    accuracy = Column(Float, default=0.0)
    num_predictions = Column(Integer, default=0)  # DEPRECATED: dead column, kept for DB migration compatibility
    brier_score = Column(Float, default=0.0)
    weight = Column(Float, default=0.0)
    last_updated = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# Compatibility Aliases
Market = WeatherMarket


class HistoricalCalibration(Base):
    """Historical calibration records for Karpathy search and backtesting."""

    __tablename__ = "historical_calibrations"

    id = Column(Integer, primary_key=True)
    city_code = Column(String, nullable=False)
    city = Column(String, nullable=True)  # Human-readable city name (e.g. "New York")
    date = Column(DateTime, nullable=False)
    metric = Column(String, nullable=False)  # "temperature_max" or "temperature_min"
    model = Column(String, nullable=False)  # e.g., "gfs_seamless", "ecmwf_ifs025"
    predicted_value = Column(Float, nullable=False)
    actual_value = Column(Float, nullable=False)
    bias = Column(Float, nullable=True)  # predicted - actual
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

