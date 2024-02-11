from threading import Thread
from multiprocessing import Queue, Process
from time import CLOCK_THREAD_CPUTIME_ID, clock_gettime
from psutil import cpu_times

class TaskIsolation(Process):
    """
    We support setting a max time for each task. This max time measures
    the amount of time that the task has actually been executing by
    the CPU.

    Our approach relies on a soft-timeout (which is the user specified time limit)
    and then a hard-timeout (by default a minute after the user specified interval). The
    soft timeout attempts to stop the task by canceling the outstanding async runloop. This works
    if the task has a lot of asyncs that return control to the runloop. If the task is saturating
    the CPU and not returning control to the runloop, then the hard-timeout will kill the task.

    If a hard timeout is triggered, we will mark this worker process as "draining". This will signal
    to the orchistrator that a new worker should be spawned instead of assigning any more work
    to this worker. We will then let the other threads drain out and then kill the worker process
    once all the threads have finished naturally or are hard-terminated.

    We boot up one worker process per core, by default. This process contains:
    - helper ping thread: communicate the health of the worker process
    - a watcher thread: to monitor the execution time of the threads
    - one thread per thread pool, is recycled after each task
        - within each worker thread: a new event loop
        - soft-timeout monitor and worker function both spawned into the event loop

    NOTE: Thread timing appears to be pretty inconsistent on OSX, with pthreads. It's possible
    to get the current thread's time but not for external callers, which is what our
    approach originally called for:
        https://man7.org/linux/man-pages/man2/getrusage.2.html

    """
    def __init__(self, task_queue: Queue):
        super().__init__()
        self.task_queue = task_queue
        self.is_draining = False

    def run(self):
        self.ping_thread = Thread(target=self.ping)
        self.ping_thread.start()

        self.watcher_thread = Thread(target=self.watch)
        self.watcher_thread.start()

        while not self.is_draining:
            task = self.task_queue.get()
            if task is None:
                break

            self.execute_task(task)

    def execute_task(self, task):
        # Update the baseline for the CPU time to measure elapsed for this
        # task alone
        process_duration = cpu_times()
        print("Starting task", process_duration)
        self.active_task = task

        self.is_draining = True
