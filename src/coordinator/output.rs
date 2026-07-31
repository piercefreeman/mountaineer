use console::{colors_enabled_stderr, Style};
use indicatif::{ProgressBar, ProgressStyle};
use mountaineer_terminal as terminal;
use std::{
    fmt::Display,
    sync::{Mutex, OnceLock},
    time::Duration,
};
use tokio::time::Instant;

#[derive(Clone, Copy)]
pub(super) enum Tone {
    Accent,
    Warning,
    Error,
    Muted,
}

impl Tone {
    fn style(self) -> Style {
        match self {
            Self::Accent => terminal::accent(),
            Self::Warning => terminal::warning(),
            Self::Error => terminal::error(),
            Self::Muted => terminal::muted(),
        }
    }
}

fn startup_spinner_slot() -> &'static Mutex<Option<ProgressBar>> {
    static SPINNER: OnceLock<Mutex<Option<ProgressBar>>> = OnceLock::new();
    SPINNER.get_or_init(|| Mutex::new(None))
}

pub(super) fn start_startup_spinner() {
    let spinner = ProgressBar::new_spinner();
    spinner.set_style(
        ProgressStyle::with_template("{spinner:.green.bold} {msg}")
            .expect("valid startup spinner template"),
    );
    spinner.set_message("Starting Mountaineer...");
    spinner.enable_steady_tick(Duration::from_millis(80));
    *startup_spinner_slot().lock().unwrap() = Some(spinner);
}

pub(super) fn finish_startup_spinner() {
    if let Some(spinner) = startup_spinner_slot().lock().unwrap().take() {
        spinner.finish_and_clear();
    }
}

fn print_status_line(line: String) {
    if let Some(spinner) = startup_spinner_slot().lock().unwrap().as_ref() {
        spinner.suspend(|| eprintln!("{line}"));
    } else {
        eprintln!("{line}");
    }
}

fn render_status(label: &str, message: impl Display, tone: Tone, color: bool) -> String {
    let continuation = "\n  ";
    let message = message
        .to_string()
        .replace("\r\n", "\n")
        .replace('\n', continuation);
    let label = tone
        .style()
        .for_stderr()
        .force_styling(color)
        .apply_to(label);
    format!("{label} {message}")
}

pub(super) fn status(tone: Tone, label: &str, message: impl Display) {
    print_status_line(render_status(label, message, tone, colors_enabled_stderr()));
}

fn render_status_with_details(
    label: &str,
    message: impl Display,
    tone: Tone,
    details: &[String],
    color: bool,
) -> String {
    let mut output = render_status(label, message, tone, color);
    for detail in details {
        output.push('\n');
        output.push_str("  ");
        output.push_str(
            &terminal::detail()
                .for_stderr()
                .force_styling(color)
                .apply_to(detail)
                .to_string(),
        );
    }
    output
}

pub(super) fn status_with_details(
    tone: Tone,
    label: &str,
    message: impl Display,
    details: &[String],
) {
    print_status_line(render_status_with_details(
        label,
        message,
        tone,
        details,
        colors_enabled_stderr(),
    ));
}

pub(super) fn link(url: impl Display) -> String {
    terminal::link().for_stderr().apply_to(url).to_string()
}

pub(super) fn emphasis(value: impl Display) -> String {
    Style::new().bold().for_stderr().apply_to(value).to_string()
}

pub(super) fn detail(value: impl Display) -> String {
    terminal::detail().for_stderr().apply_to(value).to_string()
}

pub(super) fn timing(start: Instant) -> String {
    detail(format!("in {}", format_duration(start.elapsed())))
}

fn format_duration(duration: Duration) -> String {
    if duration < Duration::from_millis(1) {
        "<1ms".to_string()
    } else if duration < Duration::from_secs(1) {
        format!("{}ms", duration.as_millis())
    } else {
        format!("{:.2}s", duration.as_secs_f64())
    }
}

pub fn report_error(program: &str, error: &dyn Display) {
    finish_startup_spinner();
    status(Tone::Error, "Error", format!("{program}: {error}"));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn status_lines_share_one_palette_and_layout() {
        assert_eq!(
            render_status("Started", "backend", Tone::Accent, false),
            "Started backend"
        );
        assert_eq!(
            render_status("Failed", "backend", Tone::Error, true),
            "\u{1b}[38;2;231;90;39m\u{1b}[1mFailed\u{1b}[0m backend"
        );
        assert_eq!(
            render_status("Failed", "first line\nsecond line", Tone::Error, false),
            "Failed first line\n  second line"
        );
        assert_eq!(format_duration(Duration::from_micros(50)), "<1ms");
        assert_eq!(format_duration(Duration::from_millis(42)), "42ms");
        assert_eq!(format_duration(Duration::from_millis(1250)), "1.25s");
        assert_eq!(
            render_status_with_details(
                "Found",
                "2 Python libraries for warm reload",
                Tone::Muted,
                &["- fastapi".to_string(), "- pydantic".to_string()],
                true,
            ),
            "\u{1b}[38;2;176;175;167mFound\u{1b}[0m 2 Python libraries for warm reload\n  \u{1b}[38;2;128;128;123m- fastapi\u{1b}[0m\n  \u{1b}[38;2;128;128;123m- pydantic\u{1b}[0m"
        );
    }

    #[test]
    fn startup_spinner_clears_when_the_server_is_ready() {
        start_startup_spinner();
        assert!(startup_spinner_slot().lock().unwrap().is_some());
        finish_startup_spinner();
        assert!(startup_spinner_slot().lock().unwrap().is_none());
    }
}
