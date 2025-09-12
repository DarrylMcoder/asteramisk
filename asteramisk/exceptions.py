class AsteramiskException(Exception):
    """Base class for all asteramisk exceptions."""
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

class HangupException(AsteramiskException):
    """ Raised when a method is called on an already hung up UI. Can be used to detect remote hangups """
    pass

class InvalidStateException(AsteramiskException):
    """ Raised when a method is called in an invalid state """
    pass
