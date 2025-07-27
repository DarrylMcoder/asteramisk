class AsteramiskException(Exception):
    """Base class for all asteramisk exceptions."""
    pass

class AGIException(AsteramiskException):
    """ An exception raised when an AGI command fails """
    pass

class GoBackException(AsteramiskException):
    """ Raised when a user of the UI wants to go back to the previous menu """
    pass

class GoToMainException(AsteramiskException):
    """ Raised when a user of the UI wants to go back to the main menu """
    pass

class CallFailedException(AsteramiskException):
    """ Raised when an outbound call fails """
    pass
