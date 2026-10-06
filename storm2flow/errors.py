class InputValidationError(ValueError):
    """Raised when a model input violates the technical specification."""


class ConservationError(ValueError):
    """Raised when a computed water balance exceeds the allowed tolerance."""
