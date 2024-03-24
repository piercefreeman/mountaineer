use criterion::{black_box, criterion_group, criterion_main, Criterion};
use std::fs::File;
use std::io::Read;

use mountaineer::strip_js_comments;

fn fresh_strip_js_comments(contents: String) -> String {
    let result = strip_js_comments(&contents, true);
    assert!(result.len() > 5000);
    result
}

fn criterion_benchmark(c: &mut Criterion) {
    // Extracted from the ".mapping" key of a full source map
    let sourcemap_path = "src/benches/fixtures/home_controller_ssr_with_react.js";
    let mut file = File::open(sourcemap_path).expect("Error opening file");
    let mut contents = String::new();
    file.read_to_string(&mut contents)
        .expect("Unable to read to string");

    c.bench_function("strip_js_comments", |b| {
        b.iter(|| fresh_strip_js_comments(black_box(contents.clone())))
    });
}

criterion_group!(benches, criterion_benchmark);
criterion_main!(benches);
