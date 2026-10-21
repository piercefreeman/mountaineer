//! Real interpreter, native thread, fork, and signal tests. Run with make test-os-level.
#![cfg(unix)]

use mountaineer_hot_reload_fork::{Config, Spawned, Strategy, Worker};
use serde_json::{json, Value};
use std::{collections::BTreeSet, fs, path::PathBuf, process::Command};
use tempfile::TempDir;
use tokio::time::{sleep, timeout, Duration};

const DEADLINE: Duration = Duration::from_secs(15);

struct Project(TempDir);

impl Project {
    fn new() -> Self {
        let project = Self(tempfile::tempdir().unwrap());
        fs::create_dir(project.path("mountaineer")).unwrap();
        project.write("mountaineer/__init__.py", "");
        project.write(
            "mountaineer/runtime.py",
            include_str!("fixtures/runtime.py"),
        );
        project
    }

    fn path(&self, name: &str) -> PathBuf {
        self.0.path().join(name)
    }

    fn write(&self, name: &str, code: &str) {
        fs::write(self.path(name), code).unwrap();
    }

    async fn spawn(&self, imports: &[&str]) -> Spawned {
        timeout(
            DEADLINE,
            Strategy::spawn(Config {
                python: "python".into(),
                project_root: self.0.path().to_owned(),
                imports: imports.iter().map(|name| name.to_string()).collect(),
            }),
        )
        .await
        .expect("import probes hung")
        .expect("fork strategy failed to start")
    }

    fn payload(&self, generation: u64, code: &str) -> PathBuf {
        let payload = self.path(&format!("payload-{generation}.json"));
        fs::write(
            &payload,
            json!({"result": self.path(&format!("result-{generation}")), "code": code}).to_string(),
        )
        .unwrap();
        payload
    }

    async fn start(&self, strategy: &mut Strategy, generation: u64, code: &str) -> (Worker, Value) {
        let worker = strategy
            .start(generation, self.payload(generation, code))
            .await
            .unwrap();
        let result = self.path(&format!("result-{generation}"));
        let ready = timeout(DEADLINE, async {
            tokio::select! {
                status = strategy.wait() => Err(format!("fork parent exited: {status:?}")),
                _ = async {
                    while !result.exists() {
                        sleep(Duration::from_millis(10)).await;
                    }
                } => Ok(serde_json::from_slice::<Value>(&fs::read(result).unwrap()).unwrap()),
            }
        })
        .await;
        match ready {
            Ok(Ok(result)) => (worker, result),
            failure => {
                strategy.shutdown().await.unwrap();
                panic!("worker {generation} failed: {failure:?}");
            }
        }
    }

    fn native_threads(&self) {
        self.write(
            "native_threads.c",
            include_str!("fixtures/native_threads.c"),
        );
        let output = Command::new("cc")
            .args([
                "-shared",
                "-fPIC",
                "-pthread",
                "native_threads.c",
                "-o",
                "native_threads.so",
            ])
            .current_dir(self.0.path())
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "C fixture failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
}

// Each case verifies the probe verdict AND that the module is usable in two workers.
async fn exercise_import(project: Project, code: &str, excluded: bool) {
    project.write(
        "subject.py",
        &format!("import os\nPID = os.getpid()\n{code}\n"),
    );
    let Spawned {
        mut strategy,
        excluded_imports,
    } = project.spawn(&["subject"]).await;
    let worker_code = format!(
        r#"
assert ('subject' in sys.modules) == {}
import subject
assert subject.PID == {}
if sys.platform == 'darwin':
    from urllib.request import getproxies_macosx_sysconf
    getproxies_macosx_sysconf()
"#,
        if excluded { "False" } else { "True" },
        if excluded {
            "os.getpid()"
        } else {
            "os.getppid()"
        },
    );
    for generation in 1..=2 {
        let (worker, _) = project.start(&mut strategy, generation, &worker_code).await;
        strategy.stop(worker).await.unwrap();
    }
    strategy.shutdown().await.unwrap();
    assert_eq!(excluded_imports.len(), usize::from(excluded));
    if excluded {
        assert_eq!(excluded_imports[0].module, "subject");
        assert!(!excluded_imports[0].reason.is_empty());
    }
}

macro_rules! import_case {
    ($name:ident, $excluded:expr, $code:expr) => {
        #[tokio::test]
        async fn $name() {
            exercise_import(Project::new(), $code, $excluded).await;
        }
    };
}

import_case!(plain_import_is_inherited, false, "VALUE = 1");
import_case!(
    python_stdout_does_not_corrupt_probe,
    false,
    "print('import output')"
);
import_case!(
    native_stdout_does_not_corrupt_probe,
    false,
    "os.write(1, b'native output\\n')"
);
import_case!(
    c_stdio_does_not_corrupt_probe,
    false,
    "import ctypes\nlib = ctypes.CDLL(None)\nlib.puts(b'C output')\nlib.fflush(None)"
);
import_case!(subprocess_output_does_not_corrupt_probe, false,
    "import subprocess, sys\nsubprocess.run([sys.executable, '-c', \"print('subprocess output')\"], check=True)");
import_case!(
    subprocess_alone_is_safe,
    false,
    "import subprocess, sys\nsubprocess.run([sys.executable, '-c', 'pass'], check=True)"
);
import_case!(subprocess_with_pipes_is_safe, false,
    "import subprocess, sys\nassert subprocess.check_output([sys.executable, '-c', \"print('ok')\"]).strip() == b'ok'");
import_case!(
    live_daemon_thread_is_deferred,
    true,
    "import threading\nthreading.Thread(target=threading.Event().wait, daemon=True).start()"
);
import_case!(
    live_non_daemon_thread_does_not_stall_probe,
    true,
    "import threading\nthreading.Thread(target=threading.Event().wait).start()"
);
import_case!(
    completed_python_thread_obeys_platform_policy,
    cfg!(target_os = "macos"),
    "import threading\nt = threading.Thread(target=lambda: None)\nt.start()\nt.join()"
);
import_case!(completed_executor_obeys_platform_policy, cfg!(target_os = "macos"),
    "from concurrent.futures import ThreadPoolExecutor\nwith ThreadPoolExecutor() as executor:\n    executor.submit(lambda: None).result()");
import_case!(
    completed_asyncio_executor_obeys_platform_policy,
    cfg!(target_os = "macos"),
    "import asyncio\nasyncio.run(asyncio.to_thread(lambda: None))"
);

#[tokio::test]
async fn live_native_thread_invisible_to_python_is_deferred() {
    let project = Project::new();
    project.native_threads();
    exercise_import(project, "import ctypes, threading\nlib = ctypes.CDLL('./native_threads.so')\nassert lib.start_thread(1) == 0\nassert threading.active_count() == 1", true).await;
}

#[tokio::test]
async fn completed_native_thread_obeys_platform_policy() {
    let project = Project::new();
    project.native_threads();
    exercise_import(
        project,
        r#"
import ctypes, sys, threading, time
lib = ctypes.CDLL('./native_threads.so')
assert lib.start_thread(0) == 0
assert threading.active_count() == 1
if sys.platform.startswith('linux'):
    # pthread_join can return before the kernel removes the task from /proc.
    deadline = time.monotonic() + 5
    while len(os.listdir('/proc/self/task')) != 1:
        assert time.monotonic() < deadline, 'joined native task did not disappear'
        time.sleep(0.001)
"#,
        cfg!(target_os = "macos"),
    )
    .await;
}

#[tokio::test]
async fn transitive_threaded_dependency_is_deferred() {
    let project = Project::new();
    project.write(
        "dependency.py",
        "import threading\nthreading.Thread(target=threading.Event().wait, daemon=True).start()\n",
    );
    exercise_import(project, "import dependency", true).await;
}

async fn failed_import(code: &str) {
    let project = Project::new();
    project.write("a_broken.py", code);
    project.write("z_safe.py", "import os\nPID = os.getpid()\n");
    let Spawned {
        mut strategy,
        excluded_imports,
    } = project.spawn(&["a_broken", "z_safe"]).await;
    project.start(&mut strategy, 1, "assert 'a_broken' not in sys.modules\nimport z_safe\nassert z_safe.PID == os.getppid()").await;
    strategy.shutdown().await.unwrap();
    assert_eq!(excluded_imports.len(), 1);
    assert_eq!(excluded_imports[0].module, "a_broken");
    assert_eq!(excluded_imports[0].thread_count, None);
    assert!(!excluded_imports[0].reason.is_empty());
}

macro_rules! failure_case {
    ($name:ident, $code:expr) => {
        #[tokio::test]
        async fn $name() {
            failed_import($code).await;
        }
    };
}

failure_case!(import_exception_is_isolated, "raise RuntimeError('broken')");
failure_case!(
    missing_transitive_import_is_isolated,
    "import nonexistent_mountaineer_dependency"
);
failure_case!(syntax_error_is_isolated, "def invalid syntax");
failure_case!(system_exit_is_isolated, "raise SystemExit(0)");
failure_case!(early_successful_exit_is_isolated, "import os\nos._exit(0)");
failure_case!(early_failed_exit_is_isolated, "import os\nos._exit(7)");
failure_case!(
    killed_probe_is_isolated,
    "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)"
);
failure_case!(thread_then_exception_is_isolated, "import threading\nthreading.Thread(target=threading.Event().wait).start()\nraise RuntimeError('after thread')");

#[tokio::test]
async fn missing_optional_import_is_excluded() {
    let project = Project::new();
    let Spawned {
        mut strategy,
        excluded_imports,
    } = project.spawn(&["nonexistent_mountaineer_dependency"]).await;
    project.start(&mut strategy, 1, "pass").await;
    strategy.shutdown().await.unwrap();
    assert_eq!(excluded_imports.len(), 1);
    assert_eq!(excluded_imports[0].thread_count, None);
}

#[tokio::test]
async fn probes_do_not_share_import_state() {
    let project = Project::new();
    for module in ["a_marker", "b_observer"] {
        project.write(&format!("{module}.py"), &format!(
            "import os\nwith open('{module}.pids', 'a') as log:\n    log.write(str(os.getpid()) + '\\n')\n"
        ));
    }
    let Spawned {
        mut strategy,
        excluded_imports,
    } = project.spawn(&["a_marker", "b_observer"]).await;
    project
        .start(
            &mut strategy,
            1,
            "assert 'a_marker' in sys.modules\nassert 'b_observer' in sys.modules",
        )
        .await;
    strategy.shutdown().await.unwrap();
    assert!(excluded_imports.is_empty());
    let pids = |module: &str| {
        fs::read_to_string(project.path(&format!("{module}.pids")))
            .unwrap()
            .lines()
            .map(str::to_owned)
            .collect::<Vec<_>>()
    };
    let a = pids("a_marker");
    let b = pids("b_observer");
    assert_eq!(a.len(), 2);
    assert_eq!(b.len(), 2);
    assert_ne!(a[0], b[0], "each probe needs a fresh interpreter");
    assert_eq!(a[1], b[1], "safe imports share the warm parent");
    assert_ne!(a[0], a[1]);
    assert_ne!(b[0], b[1]);
}

#[tokio::test]
async fn cancelled_spawn_kills_its_running_probe() {
    let project = Project::new();
    project.write("blocked.py", "import os, threading\nfrom pathlib import Path\nPath('probe.pid').write_text(str(os.getpid()))\nthreading.Event().wait()\n");
    {
        let spawning = project.spawn(&["blocked"]);
        tokio::pin!(spawning);
        tokio::select! {
            _ = &mut spawning => panic!("blocked import unexpectedly returned"),
            _ = async {
                while !project.path("probe.pid").exists() {
                    sleep(Duration::from_millis(10)).await;
                }
            } => {}
        }
    }
    let pid: u32 = fs::read_to_string(project.path("probe.pid"))
        .unwrap()
        .parse()
        .unwrap();
    assert_gone(&[json!(pid)]).await;
}

#[tokio::test]
async fn generations_have_fresh_process_state_and_one_warm_parent() {
    let project = Project::new();
    project.write("warm.py", "import os\nPID = os.getpid()\nVALUES = []\n");
    let Spawned { mut strategy, .. } = project.spawn(&["warm"]).await;
    let mut pids = BTreeSet::new();
    let mut parents = BTreeSet::new();
    for generation in 1..=10 {
        let (worker, result) = project.start(&mut strategy, generation,
            "import warm\nassert warm.PID == os.getppid()\nassert warm.VALUES == []\nwarm.VALUES.append(os.getpid())").await;
        pids.insert(result["pid"].as_u64().unwrap());
        parents.insert(result["parent"].as_u64().unwrap());
        strategy.stop(worker).await.unwrap();
    }
    strategy.shutdown().await.unwrap();
    assert_eq!(pids.len(), 10);
    assert_eq!(parents.len(), 1);
}

async fn assert_gone(pids: &[Value]) {
    let pids = serde_json::to_string(pids).unwrap();
    let output = tokio::process::Command::new("python")
        .args([
            "-c",
            r#"
import json, os, sys, time
for pid in json.loads(sys.argv[1]):
    deadline = time.monotonic() + 10
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        assert time.monotonic() < deadline, f'process {pid} survived cleanup'
        time.sleep(0.01)
"#,
            &pids,
        ])
        .output()
        .await
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[tokio::test]
async fn stopping_one_generation_preserves_its_sibling() {
    let project = Project::new();
    let Spawned { mut strategy, .. } = project.spawn(&[]).await;
    let (first, a) = project.start(&mut strategy, 1, "pass").await;
    let (_, b) = project.start(&mut strategy, 2, "pass").await;
    strategy.stop(first).await.unwrap();
    assert_gone(&[a["pid"].clone()]).await;
    project
        .start(&mut strategy, 3, &format!("os.kill({}, 0)", b["pid"]))
        .await;
    strategy.shutdown().await.unwrap();
    assert_gone(&[b["pid"].clone(), b["parent"].clone()]).await;
}

#[tokio::test]
async fn shutdown_reaps_all_active_workers() {
    let project = Project::new();
    let Spawned { mut strategy, .. } = project.spawn(&[]).await;
    let mut pids = Vec::new();
    for generation in 1..=3 {
        let (_, result) = project.start(&mut strategy, generation, "pass").await;
        pids.push(result["pid"].clone());
    }
    strategy.shutdown().await.unwrap();
    assert_gone(&pids).await;
}

#[tokio::test]
async fn commands_queued_back_to_back_do_not_stall() {
    let project = Project::new();
    let Spawned { mut strategy, .. } = project.spawn(&[]).await;
    for generation in 1..=10 {
        let worker = strategy
            .start(generation, project.payload(generation, "pass"))
            .await
            .unwrap();
        strategy.stop(worker).await.unwrap();
    }
    project.start(&mut strategy, 11, "pass").await;
    strategy.shutdown().await.unwrap();
}

async fn backend_failure(code: &str) {
    let project = Project::new();
    let Spawned { mut strategy, .. } = project.spawn(&[]).await;
    let (_, sibling) = project.start(&mut strategy, 1, "pass").await;
    strategy.start(2, project.payload(2, code)).await.unwrap();
    let status = timeout(DEADLINE, strategy.wait()).await;
    strategy.shutdown().await.unwrap();
    assert!(!status
        .expect("parent ignored failed worker")
        .unwrap()
        .success());
    assert_gone(&[sibling["pid"].clone()]).await;
}

#[tokio::test]
async fn worker_exception_fails_parent_and_reaps_sibling() {
    backend_failure("raise RuntimeError('worker failed')").await;
}

#[tokio::test]
async fn worker_clean_exit_is_still_unexpected() {
    backend_failure("os._exit(0)").await;
}

#[tokio::test]
async fn worker_sigkill_fails_parent_and_reaps_sibling() {
    backend_failure("import signal\nos.kill(os.getpid(), signal.SIGKILL)").await;
}

#[tokio::test]
async fn worker_sigint_is_reset_from_parent_ignore() {
    backend_failure("import signal\nos.kill(os.getpid(), signal.SIGINT)").await;
}

#[tokio::test]
async fn missing_payload_fails_parent() {
    let project = Project::new();
    let Spawned { mut strategy, .. } = project.spawn(&[]).await;
    strategy
        .start(1, project.path("missing.json"))
        .await
        .unwrap();
    let status = timeout(DEADLINE, strategy.wait()).await;
    strategy.shutdown().await.unwrap();
    assert!(!status.unwrap().unwrap().success());
}

#[tokio::test]
async fn malformed_payload_fails_parent() {
    let project = Project::new();
    project.write("invalid.json", "not json");
    let Spawned { mut strategy, .. } = project.spawn(&[]).await;
    strategy
        .start(1, project.path("invalid.json"))
        .await
        .unwrap();
    let status = timeout(DEADLINE, strategy.wait()).await;
    strategy.shutdown().await.unwrap();
    assert!(!status.unwrap().unwrap().success());
}

#[cfg(target_os = "macos")]
#[tokio::test]
async fn combined_imports_cannot_bypass_macos_guard() {
    let project = Project::new();
    project.write("a_marker.py", "");
    project.write("b_conditional.py", "import sys, threading\nif 'a_marker' in sys.modules:\n    t = threading.Thread(target=lambda: None)\n    t.start()\n    t.join()\n");
    let Spawned {
        mut strategy,
        excluded_imports,
    } = project.spawn(&["a_marker", "b_conditional"]).await;
    strategy.start(1, project.payload(1, "pass")).await.unwrap();
    let status = timeout(DEADLINE, strategy.wait()).await;
    strategy.shutdown().await.unwrap();
    assert!(
        excluded_imports.is_empty(),
        "individual imports should be safe"
    );
    assert!(!status.unwrap().unwrap().success());
    assert!(!project.path("result-1").exists());
}

async fn opencv(code: &str) {
    let project = Project::new();
    project.write(
        "vision.py",
        &format!("import os\nPID = os.getpid()\n{code}\n"),
    );
    let Spawned {
        mut strategy,
        excluded_imports,
    } = project.spawn(&["vision"]).await;
    let inherited = excluded_imports.is_empty();
    for generation in 1..=3 {
        let code = format!(
            r#"
assert ('vision' in sys.modules) == {inherited}
import vision, cv2, numpy as np
assert vision.PID == {pid}
pixels = np.full((1024, 1024, 3), 37, dtype=np.uint8)
blurred = cv2.GaussianBlur(pixels, (5, 5), 0)
assert np.array_equal(blurred, pixels)
gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
ok, encoded = cv2.imencode('.png', gray)
assert ok
assert np.array_equal(cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE), gray)
assert np.allclose(np.ones((64, 64)) @ np.ones((64, 64)), 64)
if sys.platform == 'darwin':
    from urllib.request import getproxies_macosx_sysconf
    getproxies_macosx_sysconf()
result['opencv'] = cv2.__version__
result['numpy'] = np.__version__
"#,
            inherited = if inherited { "True" } else { "False" },
            pid = if inherited {
                "os.getppid()"
            } else {
                "os.getpid()"
            }
        );
        let (worker, result) = project.start(&mut strategy, generation, &code).await;
        eprintln!(
            "OpenCV {}, NumPy {}, preloaded: {inherited}",
            result["opencv"], result["numpy"]
        );
        strategy.stop(worker).await.unwrap();
    }
    strategy.shutdown().await.unwrap();
}

macro_rules! opencv_case {
    ($name:ident, $code:expr) => {
        #[tokio::test]
        #[ignore = "requires numpy and opencv-python; make test-os-level includes this test"]
        async fn $name() {
            opencv($code).await;
        }
    };
}

opencv_case!(opencv_import_then_fork, "import cv2");
opencv_case!(opencv_parallel_work_then_fork, "import cv2, numpy as np\ncv2.setNumThreads(2)\ncv2.GaussianBlur(np.zeros((1024, 1024, 3), dtype=np.uint8), (5, 5), 0)");
opencv_case!(opencv_single_thread_then_fork, "import cv2, numpy as np\ncv2.setNumThreads(1)\ncv2.GaussianBlur(np.zeros((1024, 1024, 3), dtype=np.uint8), (5, 5), 0)");
opencv_case!(
    opencv_with_thread_limit_environment_then_fork,
    "os.environ['OPENCV_FOR_THREADS_NUM'] = '1'\nimport cv2"
);
opencv_case!(
    opencv_after_completed_python_thread_then_fork,
    "import threading\nt = threading.Thread(target=lambda: None)\nt.start()\nt.join()\nimport cv2"
);
opencv_case!(opencv_after_subprocess_then_fork, "import subprocess, sys\nsubprocess.run([sys.executable, '-c', 'pass'], check=True)\nimport cv2");
opencv_case!(
    numpy_blas_work_then_fork,
    "import numpy as np\nassert np.allclose(np.ones((128, 128)) @ np.ones((128, 128)), 128)"
);
