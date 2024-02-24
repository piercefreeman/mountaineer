use criterion::{black_box, criterion_group, criterion_main, Criterion};
use std::fs::File;
use std::io::Read;

use mountaineer::Ssr;

fn build_composite_file(paths: &[&str]) -> String {
    // Assume we're being called from the project root, where the Cargo.toml is located
    let base_path = "src/benches/fixtures/";
    let mut content = String::new();
    for path in paths {
        let full_path = format!("{}{}", base_path, path);
        let mut file = File::open(full_path).expect("Error opening file");
        let mut contents = String::new();
        file.read_to_string(&mut contents)
            .expect("Unable to read to string");

        content += "\n\n";
        content += &contents;
    }
    content
}

fn fresh_render(contents: String) -> String {
    // Read the "home_controller_ssr.js" file, which is a simple but relatively complete example
    // of importing the full React package and including a tsx component.
    // We need polyfills to handle some of the client-side elements that aren't included
    // in V8 by default. See the python server build pipeline for a full explanation
    // of this logic.
    let js = Ssr::new(contents, "SSR");
    return js.render_to_string(None).unwrap();
}

fn criterion_benchmark(c: &mut Criterion) {
    let contents = build_composite_file(&[
        "ssr_polyfill_archive.js",
        "home_controller_ssr_with_react.js",
    ]);

    c.bench_function("fresh_render", |b| {
        b.iter(|| fresh_render(black_box(contents.clone())))
    });
}

criterion_group!(benches, criterion_benchmark);
criterion_main!(benches);
