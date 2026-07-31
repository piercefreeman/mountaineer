//! Shared terminal styles for Mountaineer's Rust components.

#![warn(missing_docs)]

use console::{Color, Style};

fn color(red: u8, green: u8, blue: u8) -> Style {
    Style::new().fg(Color::TrueColor(red, green, blue))
}

/// Green accent used for successful or active states.
pub fn accent() -> Style {
    color(60, 200, 138).bold()
}

/// Amber accent used for warnings.
pub fn warning() -> Style {
    color(234, 153, 40).bold()
}

/// Orange-red accent used for errors.
pub fn error() -> Style {
    color(231, 90, 39).bold()
}

/// Muted foreground used for secondary labels.
pub fn muted() -> Style {
    color(176, 175, 167)
}

/// Dim foreground used for supporting details.
pub fn detail() -> Style {
    color(128, 128, 123)
}

/// Foreground used for structured payloads.
pub fn payload() -> Style {
    color(190, 190, 184)
}

/// Blue accent used for informational labels.
pub fn info() -> Style {
    color(68, 163, 248).bold()
}

/// Blue underlined style used for links.
pub fn link() -> Style {
    color(68, 163, 248).underlined()
}
