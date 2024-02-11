import ctypes
import ctypes.util
import threading
import time

libsystem_kernel_path = ctypes.util.find_library("System")
libsystem_kernel = ctypes.CDLL(libsystem_kernel_path, use_errno=True)

THREAD_BASIC_INFO = 3

class thread_basic_info(ctypes.Structure):
    _fields_ = [
        ("user_time", ctypes.c_uint32),      # user run time
        ("system_time", ctypes.c_uint32),    # system run time
        ("cpu_usage", ctypes.c_int),         # scaled cpu usage percentage
        ("policy", ctypes.c_int),            # scheduling policy in effect
        ("run_state", ctypes.c_int),         # run state
        ("flags", ctypes.c_int),             # flags
        ("suspend_count", ctypes.c_int),     # suspend count for thread
        ("sleep_time", ctypes.c_int)         # sleep time
    ]

def get_thread_cpu_time(thread_ident):
    # Fix: Properly initialize thread_info_count
    thread_info_data = thread_basic_info()
    thread_info_count = ctypes.c_int(ctypes.sizeof(thread_info_data) // ctypes.sizeof(ctypes.c_int))  # Fixed initialization

    # Convert Python thread ident to mach thread port
    libpthread = ctypes.CDLL(ctypes.util.find_library("pthread"), use_errno=True)
    thread_port = libpthread.pthread_mach_thread_np(thread_ident)
    print("thread port", thread_port)

    # Call thread_info
    result = libsystem_kernel.thread_info(thread_port, THREAD_BASIC_INFO, ctypes.byref(thread_info_data), ctypes.byref(thread_info_count))
    print("result", result)
    if result != 0:
        raise Exception(f"thread_info failed with result {result}")

    user_time = thread_info_data.user_time / 1e6  # Convert microseconds to seconds
    system_time = thread_info_data.system_time / 1e6  # Convert microseconds to seconds
    return user_time + system_time

def is_prime(n):
    if n <= 1:
        return False
    for i in range(2, n):
        if n % i == 0:
            return False
    return True

def test_isolation():
    # Usage example
    def thread_function():
        import ctypes
        import ctypes.util

        pthread_lib = ctypes.CDLL(ctypes.util.find_library('pthread'))

        # Define pthread_self function prototype
        # pthread_self() returns an unsigned long
        pthread_self = pthread_lib.pthread_self
        pthread_self.restype = ctypes.c_ulong

        # Call pthread_self to get the thread ID
        # Confirm this mirrors the ident (and it does)
        # Might be worth explicitly validating this in tests
        thread_id = pthread_self()

        print(f"Current thread ID: {thread_id}")

        import threading
        #clockid = threading.get_clockid()
        import time
        val = time.clock_gettime(time.CLOCK_THREAD_CPUTIME_ID)
        print("CPUTIME", time.CLOCK_THREAD_CPUTIME_ID)
        print("CLOCK", val)
        # clock_gettime

        # Dummy function to simulate work
        total = 0
        # Find the amount of primes
        from tqdm import tqdm
        for i in tqdm(range(500000)):
            total += is_prime(i)
        val = time.clock_gettime(time.CLOCK_THREAD_CPUTIME_ID)
        print("CLOCK2", val)

        print("Thread work done.")

    thread = threading.Thread(target=thread_function)
    thread.start()

    print("THREAD IDENT", thread.ident)

    # Now, get the CPU time of the thread
    #clk_id = time.pthread_getcpuclockid(thread.ident)
    #t1 = time.clock_gettime(clk_id)

    #cpu_time = get_thread_cpu_time(thread.ident)
    #print(f"CPU Time for thread: {cpu_time} seconds")
