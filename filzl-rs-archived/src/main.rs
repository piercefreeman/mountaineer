extern crate tree_sitter;
extern crate tree_sitter_typescript;

use std::fs;
use tree_sitter::Parser;

mod js_parser;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 2 {
        eprintln!("Usage: {} <path_to_tsx_file>", args[0]);
        std::process::exit(1);
    }

    let file_path = &args[1];
    let code = fs::read_to_string(file_path).expect("Failed to read file");

    let mut parser = Parser::new();
    let language = tree_sitter_typescript::language_tsx();
    parser
        .set_language(language)
        .expect("Error loading TSX grammar");

    let tree = parser.parse(&code, None).expect("Failed to parse code");
    let root_node = tree.root_node();

    let mut cursor = root_node.walk();
    let mut use_server_instances = Vec::new();
    js_parser::find_use_server_instances(&mut cursor, &code, &mut use_server_instances);

    let mut results = Vec::new();
    for instance in use_server_instances {
        let mut cursor = root_node.walk();
        js_parser::collect_properties(&mut cursor, &code, &instance, &mut results);
    }

    println!("Extracted values: {:?}", results);
}
