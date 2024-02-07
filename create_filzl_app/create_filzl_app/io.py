import socket


def get_free_port() -> int:
    """
    Leverage the OS-port shortcut :0 to get a free port. Return the value
    of the port that was assigned.

    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        port = s.getsockname()[1]
        s.close()
    return port
