"""Typed errors raised by the pedal client."""


class PedalError(Exception):
    """Base class for every error raised while talking to the pedal."""


class PedalTimeout(PedalError):
    """The pedal did not send the expected reply in time."""


class PedalProtocolError(PedalError):
    """A message was malformed or did not match the documented protocol."""


class ChecksumError(PedalProtocolError):
    """The CRC32 trailer of a reply did not match its payload."""


class PedalFileNotFound(PedalError):
    """The requested file is not present on the pedal."""
