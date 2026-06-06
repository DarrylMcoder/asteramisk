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
    """
    Raised when an outbound call fails.
    Use the cause and cause_txt fields to get more information.
    Explanation of the cause field can be found in the Asterisk documentation.
    cause_txt is a human readable description of the cause
    """
    def __init__(self, message, cause=None, cause_txt=None):
        super().__init__(message)
        self.cause = cause
        self.cause_txt = cause_txt

class ConfigurationException(AsteramiskException):
    """ Raised when something is incorrectly configured. E.g. a required configuration variable is missing """
    pass

class HangupException(AsteramiskException):
    """ Raised when a method is called on an already hung up UI. Can be used to detect remote hangups """
    pass

class InvalidStateException(AsteramiskException):
    """ Raised when a method is called in an invalid state """
    pass
