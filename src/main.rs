extern crate libc;

use std::os::unix::thread::JoinHandleExt;
use std::thread;
use std::time::Duration;

unsafe fn cancel_thread(thread: thread::JoinHandle<()>) {
    let handle = thread.into_pthread_t();
    libc::pthread_cancel(handle);
}

fn main() {
    // Spawn a thread that runs indefinitely and does some actual
    // calculation so we avoid sleep() freeing up any OS-level locks
    let handle = thread::spawn(|| {
        let mut prev: u64 = 0;
        let mut curr: u64 = 1;
        for _ in 0..10_000_000 {
            // Simulate heavy computation
            let next = prev.wrapping_add(curr);
            prev = curr;
            curr = next;

            // Use the result in a way that requires computation, but do it sparingly to avoid slowing down the loop too much
            if next % 100_000 == 0 {
                println!("Current Fibonacci number: {}", next);
            }
        }
    });

    thread::sleep(Duration::from_secs(5));

    // Unsafely kill the thread
    unsafe {
        cancel_thread(handle);
    }

    println!("Thread was killed");
}
