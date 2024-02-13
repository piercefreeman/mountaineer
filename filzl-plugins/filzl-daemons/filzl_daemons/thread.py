from threading import Thread

from filzl.logging import LOGGER


class AlertThread(Thread):
    """
    By default threads silently die if an exception is raised. This class
    logs the exception first.

    """
    def run(self):
        try:
            # Call the original run method
            super().run()
        except Exception as e:
            # Log the exception or handle it
            LOGGER.exception("Error in thread {self.name}: {e}")
