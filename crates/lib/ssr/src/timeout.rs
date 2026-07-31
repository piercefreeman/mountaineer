use std::sync::mpsc::{self, RecvTimeoutError};
use std::thread;
use std::time::Duration;

use crate::{Error, Result};

#[cfg(unix)]
mod platform {
    use std::os::unix::thread::JoinHandleExt;
    use std::thread::JoinHandle;

    pub(super) unsafe fn cancel_thread(thread: JoinHandle<()>) {
        /*
         * Unsafe function (probably for obvious reasons). Terminating a thread
         * on the OS level violates Rust's memory guarantees, since this can leave
         * malloc'd memory still owned by the main process. Use sparingly.
         */
        let handle = thread.into_pthread_t();
        libc::pthread_cancel(handle);
    }
}

#[cfg(windows)]
mod platform {
    use std::os::windows::io::AsRawHandle;
    use std::thread::JoinHandle;
    use winapi::um::processthreadsapi::TerminateThread;
    use winapi::um::winnt::HANDLE;

    pub(super) unsafe fn cancel_thread(thread: JoinHandle<()>) {
        let handle = thread.as_raw_handle();
        TerminateThread(handle as HANDLE, 0);
    }
}

pub(super) fn run<F, R>(function: F, timeout: Duration) -> Result<R>
where
    F: FnOnce() -> Result<R> + Send + 'static,
    R: Send + 'static,
{
    let (tx, rx) = mpsc::channel();

    let handle = thread::spawn(move || {
        let _ = tx.send(function());
    });

    match rx.recv_timeout(timeout) {
        Ok(result) => {
            let _ = handle.join();
            result
        }
        Err(RecvTimeoutError::Timeout) => {
            unsafe {
                platform::cancel_thread(handle);
            }
            Err(Error::Timeout("Function execution timed out".into()))
        }
        Err(RecvTimeoutError::Disconnected) => match handle.join() {
            Ok(()) => unreachable!("SSR worker exited without sending a result"),
            Err(panic) => std::panic::resume_unwind(panic),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn is_prime(n: u64) -> bool {
        if n <= 1 {
            return false;
        }
        if n <= 3 {
            return true;
        }
        if n.is_multiple_of(2) || n.is_multiple_of(3) {
            return false;
        }
        let mut i = 5;
        while i * i <= n {
            if n.is_multiple_of(i) || n.is_multiple_of(i + 2) {
                return false;
            }
            i += 6;
        }
        true
    }

    #[test]
    fn test_is_prime() {
        // The correctness of this function doesn't matter as much as the
        // fact that it is doing some CPU-bounded computation
        assert!(is_prime(2));
        assert!(is_prime(3));
        assert!(!is_prime(4));
    }

    #[test]
    fn test_run_thread_times_out() {
        let start = std::time::Instant::now();
        let result = run(
            || {
                let mut largest_prime = 0;
                // Outrageously large amount of processing - for all intents will
                // never complete
                for n in 2..=100_000_000 {
                    if is_prime(n) {
                        largest_prime = n;
                        if n % 1_000_000 == 0 || n == 100_000_000 {
                            println!("Current largest prime: {}", largest_prime);
                        }
                    }
                }
                Ok(largest_prime)
            },
            Duration::from_millis(500),
        );

        assert_eq!(
            result,
            Err(Error::Timeout("Function execution timed out".into()))
        );
        assert!(start.elapsed() < Duration::from_secs(1));
    }

    #[test]
    fn test_run_thread_valid() {
        let start = std::time::Instant::now();
        let result = run(|| Ok("returns instantly"), Duration::from_millis(500));

        assert_eq!(result, Ok("returns instantly"));
        assert!(start.elapsed() < Duration::from_millis(500));
    }
}
