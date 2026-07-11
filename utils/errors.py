"""Custom exception definitions."""


class BotError(Exception):
    """Base error for ASIAbot."""

    pass


class ScraperError(BotError):
    """Scraper API exception."""

    pass
