use std::path::{Path, PathBuf};
use std::sync::Arc;
use swc::{config::{IsModule, Options}, try_with_handler};
use swc_bundler::{Bundler, ModuleData, ModuleRecord};
use swc_common::{
    errors::{ColorConfig, Handler},
    FileName, FilePathMapping, SourceMap, GLOBALS,
    EsVersion,
};
use swc_ecma_parser::{lexer::Lexer, Parser, StringInput, Syntax, TsConfig};

pub struct BundleOptions {
    pub entry_points: Vec<String>,
    pub node_modules_path: String,
    pub environment: String,
    pub minify: bool,
    pub is_server: bool,
    pub live_reload_port: i32,
    pub outdir: Option<String>,
}

pub struct BundleResult {
    pub code: String,
    pub map: Option<String>,
    pub path: PathBuf,
}

pub fn bundle(options: BundleOptions) -> anyhow::Result<Vec<BundleResult>> {
    // Create source map and error handler
    let cm: Arc<SourceMap> = Arc::new(SourceMap::new(FilePathMapping::empty()));
    let handler = Handler::with_tty_emitter(ColorConfig::Auto, true, false, Some(cm.clone()));

    try_with_handler(cm.clone(), handler, |handler| {
        // Configure SWC bundler options
        let mut swc_options = Options::default();
        swc_options.config.jsc.target = Some(EsVersion::Es2020);
        
        // Set environment variables
        // Create bundler with custom module loader
        let bundler = Bundler::new(
            &cm,
            loader,
            None,
            &swc_options,
            None,
            Box::new(hook),
        );

        // Process each entry point
        let mut results = Vec::new();
        for entry_point in options.entry_points {
            let entry_path = Path::new(&entry_point);
            let output_path = if let Some(ref outdir) = options.outdir {
                PathBuf::from(outdir).join(entry_path.file_name().unwrap())
            } else {
                entry_path.with_extension("out")
            };

            // Bundle the entry point
            let bundle = bundler.bundle(entry_path)?;
            
            // Generate code and source map
            let (code, map) = bundle.emit()?;

            results.push(BundleResult {
                code,
                map: Some(map),
                path: output_path,
            });
        }

        Ok(results)
    })
}

// Custom module loader for resolving imports
fn loader(path: &Path) -> anyhow::Result<ModuleData> {
    let cm: Arc<SourceMap> = Arc::new(SourceMap::new(FilePathMapping::empty()));
    
    // Load file content
    let fm = cm.load_file(path)?;
    
    // Parse as TypeScript/JSX
    let lexer = Lexer::new(
        Syntax::Typescript(TsConfig {
            tsx: true,
            ..Default::default()
        }),
        Default::default(),
        StringInput::from(&*fm),
        None,
    );

    let mut parser = Parser::new_from(lexer);
    let module = parser.parse_module()?;

    Ok(ModuleData {
        fm,
        module,
        helpers: Default::default(),
    })
}

// Hook for module resolution and transformation
fn hook(record: &mut ModuleRecord) -> anyhow::Result<()> {
    // Here you can implement custom module resolution logic,
    // like handling node_modules, aliases, etc.
    Ok(())
}
