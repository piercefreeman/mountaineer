# Rolldown Define Test

This project demonstrates how to use the Rolldown bundler's Define feature to replace variables in JavaScript/TypeScript code.

## What it does

1. Reads the `index.ts` file that contains references to `process.env.MY_VAR`
2. Uses Rolldown's Define feature to replace occurrences of `process.env.MY_VAR` with the string "production"
3. Bundles the code and writes the output to the `dist` directory

## Requirements

- Rust and Cargo installed
- Git installed (for fetching the Rolldown dependency)

## Running the project

```bash
# Build the project
cargo build --release

# Run the executable
cargo run --release
```

## Examining the results

After running the executable:

1. Check the `dist` directory for the bundled output
2. The `process.env.MY_VAR` in the original code should be replaced with "production"

## Configuration

You can modify the value that replaces `process.env.MY_VAR` by editing the line in `src/main.rs`:

```rust
define.insert("process.env.MY_VAR".to_string(), "\"production\"".to_string());
```

Replace `"production"` with any other value as needed. 