extern crate lazy_static;
extern crate libc;

#[cfg(target_os = "macos")]
pub mod platform {
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

    pub unsafe fn get_thread_cpu_usage(thread_id: libc::pthread_t) -> Result<f64, String> {
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
            Ok(user_time + system_time)
        } else {
            println!("Failed to get thread CPU usage.");
            Err("Failed to get thread CPU usage.".to_string())
        }
    }
}

#[cfg(target_os = "linux")]
pub mod platform {
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
        Ok(ts.tv_sec + (ts.tv_nsec / 1_000_000_000f64))
    }
}
#[cfg(test)]
mod tests {
    extern crate libc;
    use super::*;
    use std::sync::mpsc;

    extern "C" {
        fn pthread_self() -> libc::pthread_t;
    }

    fn full_cpu_utilization() {
        // Heavy computation task
        let mut prime_numbers = Vec::new();
        for num in 2..100000 {
            if (2..num).all(|divisor| num % divisor != 0) {
                prime_numbers.push(num);
            }
        }
    }

    #[test]
    fn test_thread_cpu_usage() {
        // Sleep for 3 seconds (no CPU usage)
        // Then perform heavy computation
        let (tx, rx) = mpsc::channel();

        let child = thread::spawn(move || {
            unsafe {
                let thread_id = libc::pthread_self();
                tx.send(thread_id).expect("Failed to send thread id");
            }

            // Simulate idle time
            thread::sleep(Duration::from_secs(3));

            // Actually run full CPU computation
            full_cpu_utilization();
        });

        let thread_id = rx.recv().expect("Did not receive thread id");
        println!("Thread ID: {:?}", thread_id);

        // Wait for 3 seconds
        thread::sleep(Duration::from_secs(3));

        // Measure the thread; it should really be near zero but because of race conditions / CPU load
        // we just enforce it to be less than 0.1
        let cpu_usage = unsafe { platform::get_thread_cpu_usage(thread_id) };
        assert!(
            cpu_usage.is_ok(),
            "Expected CPU usage to be successfully measured"
        );
        if let Ok(usage) = cpu_usage {
            assert!(
                usage < 0.1,
                "Expected CPU usage to be less than 0.1 after idle time"
            );
        }

        // Now we wait a final 3 seconds. At this point the thread should be only working
        // on its heavy computation
        thread::sleep(Duration::from_secs(3));

        // Measure the thread; it should be near 3 seconds
        let cpu_usage = unsafe { platform::get_thread_cpu_usage(thread_id) };
        assert!(
            cpu_usage.is_ok(),
            "Expected CPU usage to be successfully measured"
        );
        if let Ok(usage) = cpu_usage {
            assert!(
                usage > 2.5,
                "Expected CPU usage to be greater than 2.5 of full computation"
            );
        }

        // Wait for the child thread to finish its computation
        child.join().expect("Child thread panicked");
    }
}
