// extern crate tree_sitter;
// extern crate tree_sitter_python;

// use std::collections::HashSet;
// use std::fs;
// use tree_sitter::{Node, Parser};

// fn main() {
//     let args: Vec<String> = std::env::args().collect();
//     if args.len() != 2 {
//         eprintln!("Usage: {} <path_to_python_file>", args[0]);
//         std::process::exit(1);
//     }

//     let file_path = &args[1];
//     let code = fs::read_to_string(file_path).expect("Failed to read file");

//     let mut parser = Parser::new();
//     let language = tree_sitter_python::language();
//     parser
//         .set_language(language)
//         .expect("Error loading Python grammar");

//     let tree = parser.parse(&code, None).expect("Failed to parse code");
//     let root_node = tree.root_node();

//     let mut main_descendants = HashSet::new();
//     find_main_descendants(&root_node, &code, &mut main_descendants);
//     println!("Main descendants: {:?}", main_descendants);

//     let mut instances = HashSet::new();
//     find_instances(&root_node, &code, &main_descendants, &mut instances);
//     println!("Instances: {:?}", instances);

//     process_calls(&root_node, &code, &instances);
// }

// fn find_main_descendants(node: &Node, code: &str, descendants: &mut HashSet<String>) {
//     println!("Node: {:?}", node.kind());
//     if node.kind() == "class_definition" {
//         let mut cursor = node.walk();
//         for child in node.children(&mut cursor) {
//             println!("Child: {:?}", child.kind());
//             if child.kind() == "base" && code[child.start_byte()..child.end_byte()].trim() == "Main"
//             {
//                 if let Some(class_name) = node.child_by_field_name("name") {
//                     descendants.insert(
//                         code[class_name.start_byte()..class_name.end_byte()]
//                             .trim()
//                             .to_string(),
//                     );
//                 }
//                 break;
//             }
//         }
//     }

//     let child_count = node.child_count();
//     for i in 0..child_count {
//         if let Some(child) = node.child(i) {
//             find_main_descendants(&child, code, descendants);
//         }
//     }
// }

// fn find_instances(
//     node: &Node,
//     code: &str,
//     descendants: &HashSet<String>,
//     instances: &mut HashSet<String>,
// ) {
//     if node.kind() == "assignment" {
//         if let Some(right_side) = node.child_by_field_name("right") {
//             if right_side.kind() == "call" {
//                 if let Some(function) = right_side.child_by_field_name("function") {
//                     if descendants.contains(
//                         &code[function.start_byte()..function.end_byte()]
//                             .trim()
//                             .to_string(),
//                     ) {
//                         if let Some(left_side) = node.child_by_field_name("left") {
//                             instances.insert(
//                                 code[left_side.start_byte()..left_side.end_byte()]
//                                     .trim()
//                                     .to_string(),
//                             );
//                         }
//                     }
//                 }
//             }
//         }
//     }

//     let child_count = node.child_count();
//     for i in 0..child_count {
//         if let Some(child) = node.child(i) {
//             find_instances(&child, code, descendants, instances);
//         }
//     }
// }

// fn process_calls(node: &Node, code: &str, instances: &HashSet<String>) {
//     if node.kind() == "call" {
//         if let Some(function) = node.child_by_field_name("function") {
//             if function.kind() == "attribute" {
//                 if let Some(object) = function.child_by_field_name("object") {
//                     let instance_name = code[object.start_byte()..object.end_byte()].trim();
//                     if instances.contains(instance_name) {
//                         println!(
//                             "Call on 'Main' descendant: {}",
//                             &code[node.start_byte()..node.end_byte()]
//                         );
//                         return;
//                     }
//                 }
//             }
//         }
//         println!("Other call: {}", &code[node.start_byte()..node.end_byte()]);
//     }

//     let child_count = node.child_count();
//     for i in 0..child_count {
//         if let Some(child) = node.child(i) {
//             process_calls(&child, code, instances);
//         }
//     }
// }
