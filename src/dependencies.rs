use petgraph::graph::{DiGraph, EdgeIndex, NodeIndex};
use petgraph::visit::{Dfs, EdgeRef, Walker};
use petgraph::Direction;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use swc_common::sync::Lrc;
use swc_common::SourceMap;
use swc_ecma_ast::{ImportDecl, Module};
use swc_ecma_parser::{lexer::Lexer, EsSyntax, Parser, Syntax, TsSyntax};
use swc_ecma_visit::{Visit, VisitWith};

struct DependencyExtractor {
    dependencies: Vec<String>,
}

impl<'a> Visit for DependencyExtractor {
    fn visit_import_decl(&mut self, import: &ImportDecl) {
        self.dependencies.push(import.src.value.to_string());
    }
}

pub struct DependencyWatcher {
    pub graph: DiGraph<PathBuf, ()>,
    node_map: HashMap<PathBuf, NodeIndex>,
    root_dir: PathBuf,
    tsconfig: Option<Value>,
}

impl DependencyWatcher {
    pub fn new(root_dir: PathBuf) -> Result<Self, String> {
        let tsconfig = Self::parse_tsconfig(&root_dir)?;
        let mut watcher = DependencyWatcher {
            graph: DiGraph::new(),
            node_map: HashMap::new(),
            root_dir,
            tsconfig,
        };
        watcher.index_all_files()?;
        Ok(watcher)
    }

    fn parse_tsconfig(root_dir: &Path) -> Result<Option<Value>, String> {
        let tsconfig_path = root_dir.join("tsconfig.json");
        if tsconfig_path.exists() {
            let tsconfig_content = fs::read_to_string(tsconfig_path)
                .map_err(|e| format!("Failed to read tsconfig.json: {:?}", e))?;
            serde_json::from_str(&tsconfig_content)
                .map_err(|e| format!("Failed to parse tsconfig.json: {:?}", e))
                .map(Some)
        } else {
            Ok(None)
        }
    }

    fn index_all_files(&mut self) -> Result<(), String> {
        let root_dir = self.root_dir.clone();
        self.index_directory(&root_dir)
    }

    fn index_directory(&mut self, dir: &Path) -> Result<(), String> {
        for entry in fs::read_dir(dir).map_err(|e| format!("Failed to read directory: {:?}", e))? {
            let entry = entry.map_err(|e| format!("Failed to read directory entry: {:?}", e))?;
            let path = entry.path();

            if path.is_dir() {
                // Ignore node_modules and hidden directories
                if path.file_name().map_or(false, |name| {
                    name == "node_modules" || name.to_string_lossy().starts_with('.')
                }) {
                    continue;
                }

                self.index_directory(&path)?;
            } else if path.extension().map_or(false, |ext| {
                ext == "ts" || ext == "tsx" || ext == "js" || ext == "jsx"
            }) {
                self.index_file(&path)?;
            }
        }
        Ok(())
    }

    pub fn update_file(&mut self, file_path: &Path) -> Result<(), String> {
        if let Some(&node_index) = self.node_map.get(file_path) {
            let outgoing_edges: Vec<EdgeIndex> = self
                .graph
                .edges_directed(node_index, Direction::Outgoing)
                .map(|e| e.id())
                .collect();
            for edge_id in outgoing_edges {
                self.graph.remove_edge(edge_id);
            }
        }

        self.index_file(file_path)
    }

    fn index_file(&mut self, file_path: &Path) -> Result<(), String> {
        let module = self.parse_js_file(file_path)?;
        let dependencies = self.extract_dependencies(&module);

        let node_index = *self
            .node_map
            .entry(file_path.to_path_buf())
            .or_insert_with(|| self.graph.add_node(file_path.to_path_buf()));

        for dep in dependencies {
            let resolved_dep = self.resolve_dependency(file_path, &dep)?;
            println!(
                "Resolved dep: {} -> {}",
                file_path.display(),
                resolved_dep.display()
            );
            let dep_index = *self
                .node_map
                .entry(resolved_dep.clone())
                .or_insert_with(|| self.graph.add_node(resolved_dep));
            self.graph.add_edge(node_index, dep_index, ());
        }

        Ok(())
    }

    fn parse_js_file(&self, file_path: &Path) -> Result<Module, String> {
        let source_map = Lrc::new(SourceMap::default());
        let source_file = source_map
            .load_file(file_path)
            .map_err(|e| format!("Failed to load file: {:?}", e))?;

        let syntax = match file_path.extension().and_then(|ext| ext.to_str()) {
            Some("js") | Some("jsx") => Syntax::Es(EsSyntax {
                jsx: true,
                ..Default::default()
            }),
            Some("ts") => Syntax::Typescript(TsSyntax {
                tsx: false,
                ..Default::default()
            }),
            Some("tsx") => Syntax::Typescript(TsSyntax {
                tsx: true,
                ..Default::default()
            }),
            _ => return Err(format!("Unsupported file type: {:?}", file_path)),
        };

        let lexer = Lexer::new(syntax, Default::default(), (&*source_file).into(), None);

        let mut parser = Parser::new_from(lexer);
        parser
            .parse_module()
            .map_err(|e| format!("Failed to parse module: {:?}", e))
    }

    fn extract_dependencies(&self, module: &Module) -> Vec<String> {
        let mut extractor = DependencyExtractor {
            dependencies: Vec::new(),
        };
        module.visit_with(&mut extractor);
        extractor.dependencies
    }

    fn resolve_dependency(
        &self,
        current_file: &Path,
        import_path: &str,
    ) -> Result<PathBuf, String> {
        if import_path.starts_with('.') {
            // Relative import
            Ok(current_file.parent().unwrap().join(import_path))
        } else if import_path.starts_with('/') {
            // Absolute import
            Ok(self.root_dir.join(import_path.strip_prefix('/').unwrap()))
        } else {
            println!("Potential alias import: {}", import_path);
            // Potential alias import
            self.resolve_alias_import(import_path)
        }
    }

    fn resolve_alias_import(&self, import_path: &str) -> Result<PathBuf, String> {
        if let Some(tsconfig) = &self.tsconfig {
            if let Some(paths) = tsconfig["compilerOptions"]["paths"].as_object() {
                for (alias, targets) in paths {
                    if import_path.starts_with(alias.trim_end_matches('*')) {
                        if let Some(target) = targets.as_array().and_then(|t| t.first()) {
                            let target_path = target.as_str().unwrap().replace("*", "");
                            let relative_path =
                                import_path.trim_start_matches(alias.trim_end_matches('*'));
                            return Ok(self.root_dir.join(target_path).join(relative_path));
                        }
                    }
                }
            }
        }

        // If no alias found, assume it's a node_modules import
        Ok(self.root_dir.join("node_modules").join(import_path))
    }

    pub fn get_affected_roots(
        &self,
        changed_file: &Path,
        root_paths: Vec<PathBuf>,
    ) -> Result<HashSet<PathBuf>, String> {
        let mut affected_roots = HashSet::new();

        // Check that the changed file is in the DAG
        if !self.node_map.contains_key(changed_file) {
            return Err(format!("Changed file not found in DAG: {:?}", changed_file));
        }

        // Check if all root_paths are in the DAG
        for root_path in &root_paths {
            if !self.node_map.contains_key(root_path) {
                return Err(format!("Root path not found in DAG: {:?}", root_path));
            }
        }

        if let Some(&node_index) = self.node_map.get(changed_file) {
            let root_indices: Vec<_> = root_paths
                .iter()
                .filter_map(|path| self.node_map.get(path))
                .cloned()
                .collect();

            for &root_index in &root_indices {
                let dfs = Dfs::new(&self.graph, root_index);
                if dfs.iter(&self.graph).any(|n| n == node_index) {
                    affected_roots.insert(self.graph[root_index].clone());
                }
            }
        }

        Ok(affected_roots)
    }

    pub fn print_dependency_tree(&self) {
        println!("Dependency Tree:");
        let root_nodes: Vec<_> = self
            .graph
            .node_indices()
            .filter(|&n| {
                self.graph
                    .neighbors_directed(n, Direction::Incoming)
                    .count()
                    == 0
            })
            .collect();

        for (i, root) in root_nodes.iter().enumerate() {
            let is_last = i == root_nodes.len() - 1;
            self.print_subtree(*root, "", is_last, &mut HashSet::new());
        }
    }

    fn print_subtree(
        &self,
        node: NodeIndex,
        indent: &str,
        is_last: bool,
        visited: &mut HashSet<NodeIndex>,
    ) {
        if visited.contains(&node) {
            println!(
                "{}{}└── [Circular Reference]",
                indent,
                if is_last { "└── " } else { "├── " }
            );
            return;
        }

        visited.insert(node);

        let node_path = &self.graph[node];
        println!(
            "{}{}{}",
            indent,
            if is_last { "└── " } else { "├── " },
            node_path.file_name().unwrap().to_string_lossy()
        );

        let children: Vec<_> = self
            .graph
            .neighbors_directed(node, Direction::Outgoing)
            .collect();
        let last_child_index = children.len().saturating_sub(1);

        for (i, child) in children.into_iter().enumerate() {
            let new_indent = format!("{}{}   ", indent, if is_last { " " } else { "│" });
            self.print_subtree(child, &new_indent, i == last_child_index, visited);
        }

        visited.remove(&node);
    }
}
