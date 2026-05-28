class BrandExtractionError(Exception):
    def __init__(self, message: str, retry_suggestion: str = "") -> None:
        super().__init__(message)
        self.retry_suggestion = retry_suggestion


class UnsupportedPlatformError(Exception):
    def __init__(self, url: str, supported: list[str] | None = None) -> None:
        self.url = url
        self.supported = supported or ["shopify", "etsy"]
        super().__init__(
            f"URL '{url}' is not a supported platform. Supported: {self.supported}"
        )
