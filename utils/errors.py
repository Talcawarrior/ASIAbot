"""Custom exception definitions."""


class BotError(Exception):
    """Base error for ASIAbot."""

    pass


class ScraperError(BotError):
    """Scraper API exception."""

    pass


class ParsingError(BotError):
    """Market parsing exception."""

    pass


class InsufficientDataError(BotError):
    """Insufficient forecasting sources exception."""

    pass
