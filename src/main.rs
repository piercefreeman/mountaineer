extern crate libc;

use std::os::unix::thread::JoinHandleExt;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

unsafe fn cancel_thread(thread: thread::JoinHandle<()>) {
    let handle = thread.into_pthread_t();
    libc::pthread_cancel(handle);
}

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

fn main() {
    let (tx, rx) = mpsc::channel();

    let handle = thread::spawn(move || {
        println!("Worker thread: Starting work.");
        let mut largest_prime = 0;

        //for n in 2..=100_000_000 {
        for n in 2..=10 {
            if is_prime(n) {
                largest_prime = n;
                if n % 1_000_000 == 0 || n == 100_000_000 {
                    println!("Current largest prime: {}", largest_prime);
                }
            }
        }
        println!("Worker thread: Work completed. {}", largest_prime);

        // Work is done, send a notification
        tx.send(()).unwrap();
        println!("Worker thread: Work completed and notification sent.");
    });

    // Main thread waits for notification with a hard timeout
    match rx.recv_timeout(Duration::from_secs(10)) {
        Ok(_) => {
            println!("Main thread: Notification received, work completed.");

            // Ensure the spawned thread has finished before exiting the program
            let _ = handle.join();
        }
        Err(e) => {
            println!(
                "Main thread: Did not receive notification within the timeout, error: {:?}",
                e
            );
            // Unsafe termination logic should go here
            println!("Main thread: Attempting to terminate the worker thread.");
            unsafe { cancel_thread(handle) };
        }
    }
}
