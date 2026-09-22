"""Reserved namespace placeholder for the On The Loop platform distribution.

See @onthelooplabs/ontheloop and https://github.com/benjamin-blake/theseus for the canonical
platform package. This placeholder is a defensive namespace hold (rec-3941) -- it carries no
platform code and no dependency.
"""

POINTER = "ontheloop"


def placeholder_identity() -> str:
    """Return the reserved placeholder identity string."""
    return POINTER
