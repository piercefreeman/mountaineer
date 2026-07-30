use console::{Color, Style};

fn color(red: u8, green: u8, blue: u8) -> Style {
    Style::new().fg(Color::TrueColor(red, green, blue))
}

pub fn accent() -> Style {
    color(60, 200, 138).bold()
}

pub fn warning() -> Style {
    color(234, 153, 40).bold()
}

pub fn error() -> Style {
    color(231, 90, 39).bold()
}

pub fn muted() -> Style {
    color(176, 175, 167)
}

pub fn detail() -> Style {
    color(128, 128, 123)
}

pub fn payload() -> Style {
    color(190, 190, 184)
}

pub fn info() -> Style {
    color(68, 163, 248).bold()
}

pub fn link() -> Style {
    color(68, 163, 248).underlined()
}
