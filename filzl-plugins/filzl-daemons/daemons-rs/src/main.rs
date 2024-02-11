extern crate lazy_static;
extern crate libc;

use lazy_static::lazy_static;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

extern "C" {
    fn pthread_self() -> libc::pthread_t;
}

#[cfg(target_os = "macos")]
mod platform {
    #[repr(C)]
    struct ThreadBasicInfo {
        user_time: libc::time_value_t,
        system_time: libc::time_value_t,
        cpu_usage: libc::integer_t,
        policy: libc::integer_t,
        run_state: libc::integer_t,
        flags: libc::integer_t,
        suspend_count: libc::integer_t,
        sleep_time: libc::integer_t,
    }

    extern "C" {
        fn pthread_mach_thread_np(thread: libc::pthread_t) -> libc::mach_port_t;
        fn thread_info(
            target_thread: libc::mach_port_t,
            flavor: libc::thread_flavor_t,
            thread_info_out: *mut libc::integer_t,
            thread_info_out_count: *mut libc::mach_msg_type_number_t,
        ) -> libc::kern_return_t;
    }

    pub unsafe fn get_thread_cpu_usage(thread_id: libc::pthread_t) {
        let thread_port = pthread_mach_thread_np(thread_id);
        let mut info = std::mem::zeroed::<ThreadBasicInfo>();
        let mut count = std::mem::size_of::<ThreadBasicInfo>() as libc::mach_msg_type_number_t
            / std::mem::size_of::<libc::integer_t>() as libc::mach_msg_type_number_t;

        let result = thread_info(
            thread_port,
            libc::THREAD_BASIC_INFO as libc::thread_flavor_t,
            &mut info as *mut _ as *mut libc::integer_t,
            &mut count,
        );

        if result == libc::KERN_SUCCESS {
            let user_time =
                info.user_time.seconds as f64 + info.user_time.microseconds as f64 / 1_000_000f64;
            let system_time = info.system_time.seconds as f64
                + info.system_time.microseconds as f64 / 1_000_000f64;
            println!(
                "CPU Time: User = {} s, System = {} s",
                user_time, system_time
            );
        } else {
            println!("Failed to get thread CPU usage.");
        }
    }
}

#[cfg(target_os = "linux")]
mod platform {
    pub unsafe fn get_thread_cpu_usage(thread_id: libc::pthread_t) {
        let mut clock_id: libc::clockid_t = 0;
        let mut ts = libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };

        libc::pthread_getcpuclockid(thread_id, &mut clock_id);
        libc::clock_gettime(clock_id, &mut ts);

        println!(
            "CPU Time: {} seconds, {} nanoseconds",
            ts.tv_sec, ts.tv_nsec
        );
    }
}

lazy_static! {
    static ref THREAD_ID: Mutex<Option<libc::pthread_t>> = Mutex::new(None);
}

unsafe fn set_global_thread_id(thread_id: libc::pthread_t) {
    let mut id_lock = THREAD_ID.lock().unwrap();
    *id_lock = Some(thread_id);
}

fn main() {
    let handle = thread::spawn(|| {
        unsafe {
            // Set the spawned thread's ID in the global variable
            set_global_thread_id(pthread_self());
        }

        // Simulate work
        thread::sleep(Duration::from_secs(3));

        // Perform some computation
        let mut primes = Vec::new();
        for i in 2..1000000 {
            if !primes.iter().any(|&p| i % p == 0) {
                primes.push(i);
            }
        }

        println!("Calculated {} primes.", primes.len());
    });

    // Ensure the spawned thread has time to set its ID
    thread::sleep(Duration::from_secs(1));

    // Attempt to read the thread ID set by the spawned thread
    let spawned_thread_id = THREAD_ID.lock().unwrap();
    match *spawned_thread_id {
        Some(id) => {
            println!("Spawned thread ID: {:?}", id);
            unsafe {
                platform::get_thread_cpu_usage(id);
            }
            thread::sleep(Duration::from_secs(5));
            unsafe {
                platform::get_thread_cpu_usage(id);
            }
        }
        None => println!("Failed to obtain spawned thread ID."),
    }

    handle.join().unwrap();
}
