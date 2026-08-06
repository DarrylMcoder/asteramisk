import logging

from .communicator import Communicator
from .server import Server

__all__ = [
    "Communicator",
    "Server",
]

NOISY_DEPENDENCIES = [
    "panoramisk",
    "websockets",
    "asteramisk.internal",
]

# Quiet these noisy libraries by default
# They make too many logs

for dependency in NOISY_DEPENDENCIES:
    logging.getLogger(dependency).setLevel(logging.WARNING)
