use std::result::Result;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use crate::errors::AppError;

#[cfg(unix)]
mod platform {
    use std::os::unix::thread::JoinHandleExt;
    use std::thread::JoinHandle;

    pub unsafe fn cancel_thread(thread: JoinHandle<()>) {
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
    // nits
    extern crate winapi;
    use std::os::windows::io::AsRawHandle;
    use std::thread::JoinHandle;
    use winapi::um::processthreadsapi::TerminateThread;
    use winapi::um::winnt::HANDLE;

    pub unsafe fn cancel_thread(thread: JoinHandle<()>) {
        let handle = thread.as_raw_handle();
        TerminateThread(handle as HANDLE, 0);
    }
}

pub fn run_thread_with_timeout<F, R>(func: F, timeout: Duration) -> Result<R, AppError>
where
    F: FnOnce() -> Result<R, AppError> + Send + 'static,
    R: Send + 'static,
{
    let (tx, rx) = mpsc::channel();

    // Spawn a new thread to run the provided function
    let handle = thread::spawn(move || {
        let result = func();
        tx.send(result).expect("Failed to send result");
    });

    match rx.recv_timeout(timeout) {
        Ok(result) => {
            let _ = handle.join();
            result
        } // Function completed within timeout
        Err(_) => {
            unsafe {
                platform::cancel_thread(handle);
            }
            Err(AppError::HardTimeoutError(
                "Function execution timed out".into(),
            ))
        } // Timeout occurred, we should cancel the thread and return
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
        if n % 2 == 0 || n % 3 == 0 {
            return false;
        }
        let mut i = 5;
        while i * i <= n {
            if n % i == 0 || n % (i + 2) == 0 {
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
        assert_eq!(is_prime(2), true);
        assert_eq!(is_prime(3), true);
        assert_eq!(is_prime(4), false);
    }

    #[test]
    fn test_run_thread_times_out() {
        let start = std::time::Instant::now();
        let result = run_thread_with_timeout(
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
            Err(AppError::HardTimeoutError(
                "Function execution timed out".into()
            ))
        );
        assert!(start.elapsed() < Duration::from_secs(1));
    }

    #[test]
    fn test_run_thread_valid() {
        let start = std::time::Instant::now();
        let result = run_thread_with_timeout(
            || return Ok("returns instantly"),
            Duration::from_millis(500),
        );

        assert_eq!(result, Ok("returns instantly"));
        assert!(start.elapsed() < Duration::from_millis(500));
    }
}
