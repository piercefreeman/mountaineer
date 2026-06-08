# Agent Guide

## Testing

- Prefer behavioral tests that exercise generated output or runtime behavior through the public API.
- Avoid hyper-specialized string-presence tests for generated files. They are brittle and should only be used when the literal text is the behavior being tested.
