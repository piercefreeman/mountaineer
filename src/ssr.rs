//
// Copyright (c) 2023 Pierce Freeman <pierce@freeman.vc>
// Copyright (c) 2018 Valerio Ageno <valerioageno@yahoo.it>
//
// Permission is hereby granted, free of charge, to any
// person obtaining a copy of this software and associated
// documentation files (the "Software"), to deal in the
// Software without restriction, including without
// limitation the rights to use, copy, modify, merge,
// publish, distribute, sublicense, and/or sell copies of
// the Software, and to permit persons to whom the Software
// is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice
// shall be included in all copies or substantial portions
// of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF
// ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
// TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
// PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
// SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
// CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
// OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR
// IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
// DEALINGS IN THE SOFTWARE.

use crate::errors::AppError;
use crate::logging::StdoutWrapper;
use crate::timeout;
use std::collections::HashMap;
use std::io::Write;
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[derive(Clone, Debug, PartialEq)]
pub struct Ssr<'a> {
    // TODO: Check if better Box<str> instead of String
    source: String,
    entry_point: &'a str,
}

struct LoggerData {
    console_type: String,
    stdout: Arc<Mutex<dyn Write + 'static>>,
}

// Ensure that LoggerData can be sent safely across threads.
unsafe impl Send for LoggerData {}

impl<'a> Ssr<'a> {
    /// Create an instance of the Ssr struct instanciate the v8 platform as well.
    pub fn new(source: String, entry_point: &'a str) -> Self {
        Self::init_platform();

        Ssr {
            source,
            entry_point,
        }
    }

    fn init_platform() {
        lazy_static! {
          static ref INIT_PLATFORM: () = {
              // Include ICU data file.
              // https://github.com/denoland/deno_core/blob/d8e13061571e587b92487d391861faa40bd84a6f/core/runtime/setup.rs#L21
              v8::icu::set_common_data_73(deno_core_icudata::ICU_DATA).unwrap();

              //Initialize a new V8 platform
              let platform = v8::new_default_platform(0, false).make_shared();
              v8::V8::initialize_platform(platform);
              v8::V8::initialize();
          };
        }

        lazy_static::initialize(&INIT_PLATFORM);
    }

    /// Evaluates the JS source code instanciate in the Ssr struct
    /// "enrty_point" is the variable name set from the frontend bundler used. <a href="https://github.com/Valerioageno/ssr-rs/blob/main/client/webpack.ssr.js" target="_blank">Here</a> an example from webpack.
    pub fn render_to_string(&self, params: Option<&str>) -> Result<String, AppError> {
        Self::render(
            self.source.clone(),
            self.entry_point,
            params,
            StdoutWrapper::new().get_arc(),
        )
    }

    fn render(
        source: String,
        entry_point: &str,
        params: Option<&str>,
        stdout: Arc<Mutex<dyn Write + 'static>>,
    ) -> Result<String, AppError> {
        /*
         * Main entrypoint for rendering, takes a source string (containing one or many functions) and
         * an entry point (ie. function name to execute) and returns the result of the execution as
         * a string.
         */
        // let isolate_params = v8::CreateParams::default().heap_limits(0, 2000 * 1024 * 1024);
        let isolate = &mut v8::Isolate::new(Default::default());
        let handle_scope = &mut v8::HandleScope::new(isolate);
        let mut context = v8::Context::new(handle_scope);
        let scope = &mut v8::ContextScope::new(handle_scope, context);

        // Add logging support
        Self::inject_logger(&mut context, scope, stdout);

        // Encapsulate all V8 operations that might throw exceptions within this TryCatch block
        let try_catch = &mut v8::TryCatch::new(scope);

        let code = match v8::String::new(try_catch, &format!("{};{}", source, entry_point)) {
            Some(code) => code,
            None => {
                // This typically shouldn't fail unless there's a serious issue (like out of memory),
                // so we don't handle it specifically with try_catch.
                return Err(AppError::V8ExceptionError(
                    "Failed to create code string".into(),
                ));
            }
        };

        let script = if let Some(s) = v8::Script::compile(try_catch, code, None) {
            s
        } else {
            return Err(AppError::V8ExceptionError(Self::extract_exception_message(
                try_catch,
                "Script compilation failed",
            )));
        };

        let result = if let Some(r) = script.run(try_catch) {
            r
        } else {
            return Err(AppError::V8ExceptionError(Self::extract_exception_message(
                try_catch,
                "Script execution failed",
            )));
        };

        let object = if let Some(obj) = result.to_object(try_catch) {
            obj
        } else {
            return Err(AppError::V8ExceptionError(Self::extract_exception_message(
                try_catch,
                "Result is not an object",
            )));
        };

        // Assuming `create_fn_map` exists and properly implemented
        let fn_map = Self::create_fn_map(try_catch, object);

        let params_v8 = match v8::String::new(try_catch, params.unwrap_or_default()) {
            Some(s) => s.into(),
            None => v8::undefined(try_catch).into(),
        };

        let mut rendered = String::new();

        for (key, func) in fn_map {
            let key_str = key; // Assuming key is already a Rust String
            let result = func.call(try_catch, object.into(), &[params_v8]);
            if try_catch.has_caught() {
                return Err(AppError::V8ExceptionError(Self::extract_exception_message(
                    try_catch,
                    &format!("Error calling function '{}'", key_str),
                )));
            }

            let result_str = result
                .expect("Function call did not return a value")
                .to_rust_string_lossy(try_catch);

            rendered.push_str(&result_str);
        }

        Ok(rendered)
    }

    fn inject_logger(
        context: &mut v8::Local<'_, v8::Context>,
        scope: &mut v8::ContextScope<'_, v8::HandleScope<'_>>,
        stdout: Arc<Mutex<dyn Write + 'static>>,
    ) {
        let console_types = vec!["log", "warn", "info", "debug", "error"];
        let global = context.global(scope);
        let console_key =
            v8::String::new(scope, "console").unwrap_or_else(|| v8::String::empty(scope));
        let console_obj = global
            .get(scope, console_key.into())
            .and_then(|v| v.to_object(scope))
            .unwrap_or_else(|| {
                let obj = v8::ObjectTemplate::new(scope).new_instance(scope).unwrap();
                global.set(scope, console_key.into(), obj.into());
                obj
            });

        for console_type in console_types {
            let logger_data = LoggerData {
                console_type: console_type.to_string(),
                stdout: stdout.clone(),
            };
            let logger_data_external =
                v8::External::new(scope, Box::into_raw(Box::new(logger_data)) as *mut _);

            // Normally, we'd just use a closure to pass the console data into our handler function.
            // However, the Function() syntax in V8 relies on us passing a raw function _pointer_ into
            // the C++ engine. Closures in rust create an AnonymousClosure struct which isn't compatible
            // with the function interface. We instead pass our necessary variables into a v8::External data
            // structure and then extract them in our handler function.
            // If we need to pass other rust-native types in the future, we can do something similar
            // and just pass the pointers.
            let logger_fn = v8::Function::builder(
                move |scope: &mut v8::HandleScope,
                      args: v8::FunctionCallbackArguments,
                      mut ret_val: v8::ReturnValue| {
                    let data = args.data();
                    let logger_data = if data.is_external() {
                        let external = unsafe { v8::Local::<v8::External>::cast(data) };
                        let logger_data_ptr = external.value();
                        unsafe { &*(logger_data_ptr as *const LoggerData) }
                    } else {
                        panic!("Expected logger data to be passed as external data");
                    };

                    let log_message = (0..args.length())
                        .map(|i| {
                            args.get(i)
                                .to_string(scope)
                                .unwrap()
                                .to_rust_string_lossy(scope)
                        })
                        .collect::<Vec<String>>()
                        .join(" ");

                    let mut stdout_lock = logger_data.stdout.lock().unwrap();
                    writeln!(
                        stdout_lock,
                        "ssr console [{}]: {}",
                        logger_data.console_type, log_message
                    )
                    .expect("Failed to write to stdout");

                    ret_val.set_undefined();
                },
            )
            .data(logger_data_external.into())
            .build(scope)
            .unwrap();

            let console_type_key = v8::String::new(scope, console_type).unwrap();
            console_obj.set(scope, console_type_key.into(), logger_fn.into());
        }
    }

    fn extract_exception_message(
        try_catch: &mut v8::TryCatch<v8::HandleScope>,
        user_msg: &str,
    ) -> String {
        if let Some(exception) = try_catch.exception() {
            let exceptions = try_catch.stack_trace();
            let mut scope = v8::EscapableHandleScope::new(try_catch);

            // Directly use try_catch for extracting the exception message
            let msg = exception.to_rust_string_lossy(&mut scope);

            // Directly use try_catch to get the stack trace if available
            let maybe_stack = exceptions.map_or_else(String::new, |trace| {
                format!("\nStack: {}", trace.to_rust_string_lossy(&mut scope))
            });

            format!("{}: {}{}", user_msg, msg, maybe_stack)
        } else {
            // Return a default message or further handle the lack of exception details
            "An unknown error occurred".to_string()
        }
    }

    fn create_fn_map<'b>(
        scope: &mut v8::TryCatch<'b, v8::HandleScope>,
        object: v8::Local<v8::Object>,
    ) -> HashMap<String, v8::Local<'b, v8::Function>> {
        let mut fn_map: HashMap<String, v8::Local<v8::Function>> = HashMap::new();

        if let Some(props) = object.get_own_property_names(scope, Default::default()) {
            fn_map = Some(props)
                .iter()
                .enumerate()
                .map(|(i, &p)| {
                    let name = p.get_index(scope, i as u32).unwrap();

                    //A HandleScope which first allocates a handle in the current scope which will be later filled with the escape value.
                    let mut scope = v8::EscapableHandleScope::new(scope);

                    let func = object.get(&mut scope, name).unwrap();

                    let func = unsafe { v8::Local::<v8::Function>::cast(func) };

                    (
                        name.to_string(&mut scope)
                            .unwrap()
                            .to_rust_string_lossy(&mut scope),
                        scope.escape(func),
                    )
                })
                .collect();
        }

        fn_map
    }
}

pub fn run_ssr(js_string: String, hard_timeout: u64) -> Result<String, AppError> {
    if hard_timeout > 0 {
        timeout::run_thread_with_timeout(
            || {
                let js = Ssr::new(js_string, "SSR");
                js.render_to_string(None)
            },
            Duration::from_millis(hard_timeout),
        )
    } else {
        // Call inline, no timeout
        let js = Ssr::new(js_string, "SSR");
        js.render_to_string(None)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn render_no_timeout() {
        let js_string = r##"var SSR = { renderToString: () => "<html></html>" };"##.to_string();
        let hard_timeout = 0;

        let result = run_ssr(js_string, hard_timeout).unwrap();
        assert_eq!(result, "<html></html>");
    }

    #[test]
    fn render_with_timeout() {
        let js_string = r##"var SSR = { renderToString: () => "<html></html>" };"##.to_string();
        let hard_timeout = 2000;

        let result = run_ssr(js_string, hard_timeout).unwrap();
        assert_eq!(result, "<html></html>");
    }

    #[test]
    fn check_ssr_struct_instance() {
        let js = Ssr::new(
            r##"var SSR = {x: () => "<html></html>"};"##.to_string(),
            "SSR",
        );

        assert_eq!(
            js,
            Ssr {
                source: r##"var SSR = {x: () => "<html></html>"};"##.to_string(),
                entry_point: "SSR"
            }
        )
    }

    #[test]
    fn check_exception() {
        let js = Ssr::new(
            r##"
                var SSR = {
                    x: () => {
                        throw new Error('custom_error_text')
                    }
                };"##
                .to_string(),
            "SSR",
        );
        let result = js.render_to_string(None);

        assert_eq!(
            result,
            Err(AppError::V8ExceptionError("Error calling function 'x': Error: custom_error_text\nStack: Error: custom_error_text\n    at Object.x (<anonymous>:4:31)".into()))
        )
    }

    #[test]
    fn test_render_to_string() {
        let js = Ssr::new(
            r##"
                var SSR = {
                    x: () => "<html></html>"
                };"##
                .to_string(),
            "SSR",
        );
        let result = js.render_to_string(None);

        assert_eq!(result, Ok("<html></html>".to_string()))
    }

    #[test]
    fn test_log_to_stdout() {
        // Create a synthetic stdout that we can inspect
        let stdout = Arc::new(Mutex::new(Vec::new()));

        Ssr::init_platform();
        let result = Ssr::render(
            r##"
                var SSR = {
                    x: () => {
                        console.log('test log');
                        return "<html></html>"
                    }
                };"##
                .to_string(),
            "SSR",
            None,
            stdout.clone(),
        );

        let result_vector = stdout.lock().unwrap();

        assert_eq!(result, Ok("<html></html>".to_string()));
        assert_eq!(
            String::from_utf8_lossy(&*result_vector),
            "ssr console [log]: test log\n"
        );
    }

    #[test]
    fn test_timezone_succeeds() {
        // More context:
        // https://github.com/denoland/rusty_v8/issues/1444
        // https://github.com/denoland/rusty_v8/pull/603
        let js = Ssr::new(
            r##"
                var SSR = {
                    x: () => {
                        const value = new Intl.DateTimeFormat(void 0, {
                            timeZone: "America/Los_Angeles",
                        });
                        return value;
                    }
                };"##
                .to_string(),
            "SSR",
        );
        let result = js.render_to_string(None);

        assert_eq!(result, Ok("[object Intl.DateTimeFormat]".to_string()))
    }
}
