class BaseSecurityError(Exception):

    message = "Security error."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.message
        super().__init__(self.message)


class TokenExpiredError(BaseSecurityError):
    message = "Token has expired."


class InvalidTokenError(BaseSecurityError):
    message = "Invalid token."
