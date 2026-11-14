class ApiError(Exception):
    """Raise this in an endpoint to return the contract's error shape: {"error": code, "message": sentence}."""

    def __init__(self, status: int, error: str, message: str):
        self.status, self.error, self.message = status, error, message
