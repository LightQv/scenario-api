"""
Custom exception class
"""


class CustomExceptionError(Exception):
    """
    Custom exception class
    """

    def __init__(
        self,
        error_dict: dict,
        value: any = None,
    ):
        self.key = error_dict.get("key", "unknown_error_key")
        self.message = error_dict.get("message", "An unexpected error occurred.")
        self.status_code = error_dict.get("status_code", 400)
        self.value = value
        super().__init__(self.key)
