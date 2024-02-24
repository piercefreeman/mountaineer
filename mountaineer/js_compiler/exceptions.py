class BuildProcessException(Exception):
    """
    Build error raised with this exception will directly log without
    a stack trace, since seeing the python layer isn't helpful.
    """

    pass
