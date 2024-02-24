use criterion::{black_box, criterion_group, criterion_main, Criterion};
use std::fs::File;
use std::io::Read;

use mountaineer::{SourceMapParser, VLQDecoder};

fn fresh_parse_mapping(
    contents: String,
) -> std::collections::HashMap<(i32, i32), mountaineer::MapMetadata> {
    let mut parser = SourceMapParser::new(VLQDecoder::new());
    let result = parser.parse_mapping(&contents).unwrap();

    // Ensure the result actually parsed
    assert!(result.len() > 5000);

    return result;
}

fn criterion_benchmark(c: &mut Criterion) {
    // Extracted from the ".mapping" key of a full source map
    let sourcemap_path = "src/benches/fixtures/complex_sourcemap_mapping.txt";
    let mut file = File::open(sourcemap_path).expect("Error opening file");
    let mut contents = String::new();
    file.read_to_string(&mut contents)
        .expect("Unable to read to string");

    c.bench_function("parse_source_map_mapping", |b| {
        b.iter(|| fresh_parse_mapping(black_box(contents.clone())))
    });
}

criterion_group!(benches, criterion_benchmark);
criterion_main!(benches);
