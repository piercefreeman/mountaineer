//! Embedded-V8 server-side rendering for Mountaineer.

#![warn(missing_docs)]

mod error;
mod renderer;
mod timeout;

use log::debug;
use std::time::Duration;

pub use error::Error;
pub use renderer::Ssr;

/// Result returned by the SSR component.
pub type Result<T> = std::result::Result<T, Error>;

/// Renders the conventional `SSR` entry point, optionally enforcing a hard timeout.
pub fn render(source: String, hard_timeout: Option<Duration>) -> Result<String> {
    // V8 must initialize on the calling thread before timeout work is delegated.
    // https://github.com/denoland/rusty_v8/issues/1381
    renderer::initialize();
    debug!("SSR execution starting with hard timeout: {hard_timeout:?}");

    if let Some(hard_timeout) = hard_timeout {
        timeout::run(
            || Ssr::new(source, "SSR").render_to_string(None),
            hard_timeout,
        )
    } else {
        Ssr::new(source, "SSR").render_to_string(None)
    }
}
