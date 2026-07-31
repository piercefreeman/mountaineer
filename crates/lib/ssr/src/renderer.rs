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

use crate::{Error, Result};
use std::io::Write;
use std::sync::{Arc, Mutex, Once};

type Writer = Arc<Mutex<dyn Write + Send + 'static>>;

/// A JavaScript source bundle and the object whose functions produce rendered output.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Ssr<'a> {
    source: String,
    entry_point: &'a str,
}

struct LoggerData {
    console_type: &'static str,
    stdout: Writer,
}

pub(crate) fn initialize() {
    static INIT: Once = Once::new();
    INIT.call_once(|| {
        v8::icu::set_common_data_73(deno_core_icudata::ICU_DATA).unwrap();
        let platform = v8::new_default_platform(0, false).make_shared();
        v8::V8::initialize_platform(platform);
        v8::V8::initialize();
    });
}

impl<'a> Ssr<'a> {
    /// Creates an SSR bundle that resolves functions from `entry_point`.
    pub fn new(source: String, entry_point: &'a str) -> Self {
        Self {
            source,
            entry_point,
        }
    }

    /// Executes every function exported by the entry-point object and concatenates the results.
    pub fn render_to_string(&self, params: Option<&str>) -> Result<String> {
        Self::render(
            &self.source,
            self.entry_point,
            params,
            Arc::new(Mutex::new(std::io::stdout())),
        )
    }

    fn render(
        source: &str,
        entry_point: &str,
        params: Option<&str>,
        stdout: Writer,
    ) -> Result<String> {
        initialize();

        /*
         * Main entrypoint for rendering, takes a source string (containing one or many functions) and
         * an entry point (ie. function name to execute) and returns the result of the execution as
         * a string.
         */
        // let isolate_params = v8::CreateParams::default().heap_limits(0, 2000 * 1024 * 1024);
        let isolate = &mut v8::Isolate::new(Default::default());
        let handle_scope = &mut v8::HandleScope::new(isolate);
        let mut context = v8::Context::new(handle_scope, Default::default());
        let scope = &mut v8::ContextScope::new(handle_scope, context);

        let logger_data =
            ["log", "warn", "info", "debug", "error"].map(|console_type| LoggerData {
                console_type,
                stdout: stdout.clone(),
            });
        Self::inject_logger(&mut context, scope, &logger_data);

        // Encapsulate all V8 operations that might throw exceptions within this TryCatch block
        let try_catch = &mut v8::TryCatch::new(scope);

        let code = match v8::String::new(try_catch, &format!("{source}\n;{entry_point}")) {
            Some(code) => code,
            None => {
                // This typically shouldn't fail unless there's a serious issue (like out of memory),
                // so we don't handle it specifically with try_catch.
                return Err(Error::JavaScript("Failed to create code string".into()));
            }
        };

        let script = if let Some(s) = v8::Script::compile(try_catch, code, None) {
            s
        } else {
            return Err(Error::JavaScript(Self::extract_exception_message(
                try_catch,
                "Script compilation failed",
            )));
        };

        let result = if let Some(r) = script.run(try_catch) {
            r
        } else {
            return Err(Error::JavaScript(Self::extract_exception_message(
                try_catch,
                "Script execution failed",
            )));
        };

        let object = if let Some(obj) = result.to_object(try_catch) {
            obj
        } else {
            return Err(Error::JavaScript(Self::extract_exception_message(
                try_catch,
                "Result is not an object",
            )));
        };

        let functions = Self::entrypoint_functions(try_catch, object)?;

        let params_v8 = match v8::String::new(try_catch, params.unwrap_or_default()) {
            Some(s) => s.into(),
            None => v8::undefined(try_catch).into(),
        };

        let mut rendered = String::new();

        for (name, function) in functions {
            let result = function.call(try_catch, object.into(), &[params_v8]);
            if try_catch.has_caught() {
                return Err(Error::JavaScript(Self::extract_exception_message(
                    try_catch,
                    &format!("Error calling function '{name}'"),
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
        logger_data: &[LoggerData],
    ) {
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

        for data in logger_data {
            let logger_data_external =
                v8::External::new(scope, data as *const LoggerData as *mut std::ffi::c_void);

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
                        let external = v8::Local::<v8::External>::try_from(data).unwrap();
                        let logger_data_ptr = external.value();
                        unsafe { &*(logger_data_ptr as *const LoggerData) }
                    } else {
                        panic!("Expected logger data to be passed as external data");
                    };

                    let values = (0..args.length())
                        .map(|i| {
                            let value = args.get(i);
                            (
                                Self::format_console_value(scope, value),
                                value.is_object() && !value.is_native_error(),
                            )
                        })
                        .collect::<Vec<_>>();

                    let mut stdout_lock = logger_data.stdout.lock().unwrap();
                    writeln!(
                        stdout_lock,
                        "{}",
                        Self::render_console_line(
                            logger_data.console_type,
                            &values,
                            console::colors_enabled(),
                        )
                    )
                    .expect("Failed to write to stdout");

                    ret_val.set_undefined();
                },
            )
            .data(logger_data_external.into())
            .build(scope)
            .unwrap();

            let console_type_key = v8::String::new(scope, data.console_type).unwrap();
            console_obj.set(scope, console_type_key.into(), logger_fn.into());
        }
    }

    fn render_console_line(console_type: &str, values: &[(String, bool)], color: bool) -> String {
        let level_style = match console_type {
            "warn" => mountaineer_terminal::warning(),
            "error" => mountaineer_terminal::error(),
            _ => mountaineer_terminal::muted(),
        };
        let prefix = format!(
            "  {} {}",
            mountaineer_terminal::info()
                .force_styling(color)
                .apply_to("[SSR]"),
            level_style
                .force_styling(color)
                .apply_to(format!("[{console_type}]"))
        );
        let message = values
            .iter()
            .map(|(value, structured)| {
                if color && *structured {
                    mountaineer_terminal::payload()
                        .force_styling(true)
                        .apply_to(value)
                        .to_string()
                } else {
                    value.clone()
                }
            })
            .collect::<Vec<_>>()
            .join(" ");
        format!("{prefix} {message}")
    }

    fn format_console_value(scope: &mut v8::HandleScope, value: v8::Local<v8::Value>) -> String {
        if value.is_object() && !value.is_native_error() {
            let serialized = {
                let try_catch = &mut v8::TryCatch::new(scope);
                v8::json::stringify(try_catch, value)
                    .map(|json| json.to_rust_string_lossy(try_catch))
            };
            if let Some(serialized) = serialized {
                return serialized;
            }
        }
        value
            .to_string(scope)
            .map(|text| text.to_rust_string_lossy(scope))
            .unwrap_or_else(|| "<unprintable>".to_string())
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

            format!("{user_msg}: {msg}{maybe_stack}")
        } else {
            // Return a default message or further handle the lack of exception details
            "An unknown error occurred".to_string()
        }
    }

    fn entrypoint_functions<'b>(
        scope: &mut v8::TryCatch<'b, v8::HandleScope>,
        object: v8::Local<v8::Object>,
    ) -> Result<Vec<(String, v8::Local<'b, v8::Function>)>> {
        let Some(properties) = object.get_own_property_names(scope, Default::default()) else {
            return Err(Error::JavaScript(Self::extract_exception_message(
                scope,
                "Failed to inspect the SSR entry point",
            )));
        };
        let mut functions = Vec::with_capacity(properties.length() as usize);

        for index in 0..properties.length() {
            let Some(property) = properties.get_index(scope, index) else {
                return Err(Error::JavaScript(format!(
                    "Failed to read SSR entry point property {index}"
                )));
            };
            let name = property
                .to_string(scope)
                .map(|name| name.to_rust_string_lossy(scope))
                .unwrap_or_else(|| index.to_string());
            let mut child_scope = v8::EscapableHandleScope::new(scope);
            let Some(value) = object.get(&mut child_scope, property) else {
                return Err(Error::JavaScript(format!(
                    "Failed to read SSR entry point property '{name}'"
                )));
            };
            let function = v8::Local::<v8::Function>::try_from(value).map_err(|_| {
                Error::JavaScript(format!(
                    "SSR entry point property '{name}' is not a function"
                ))
            })?;
            functions.push((name, child_scope.escape(function)));
        }

        Ok(functions)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn render_no_timeout() {
        let js_string = r##"var SSR = { renderToString: () => "<html></html>" };"##.to_string();
        let result = crate::render(js_string, None).unwrap();
        assert_eq!(result, "<html></html>");
    }

    #[test]
    fn render_ignores_a_trailing_line_comment() {
        let js = Ssr::new(
            "var SSR = { renderToString: () => \"<html></html>\" };\n//# sourceMappingURL=ssr.js.map"
                .to_string(),
            "SSR",
        );

        assert_eq!(js.render_to_string(None).unwrap(), "<html></html>");
    }

    #[test]
    fn render_with_timeout() {
        let js_string = r##"var SSR = { renderToString: () => "<html></html>" };"##.to_string();
        let result = crate::render(js_string, Some(Duration::from_millis(2000))).unwrap();
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
            Err(Error::JavaScript("Error calling function 'x': Error: custom_error_text\nStack: Error: custom_error_text\n    at Object.x (<anonymous>:4:31)".into()))
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
    fn renders_entrypoint_functions_in_export_order() {
        let js = Ssr::new(
            "var SSR = { head: () => '<head>', body: () => '<body>' };".to_string(),
            "SSR",
        );

        assert_eq!(js.render_to_string(None).unwrap(), "<head><body>");
    }

    #[test]
    fn rejects_non_function_entrypoint_properties() {
        let js = Ssr::new("var SSR = { renderToString: 42 };".to_string(), "SSR");

        assert!(matches!(
            js.render_to_string(None),
            Err(Error::JavaScript(message)) if message.contains("is not a function")
        ));
    }

    #[test]
    fn test_log_to_stdout() {
        // Create a synthetic stdout that we can inspect
        let stdout = Arc::new(Mutex::new(Vec::new()));

        let result = Ssr::render(
            r##"
                var SSR = {
                    x: () => {
                        console.log('test log', {
                            answer: 42,
                            nested: { ready: true },
                        });
                        return "<html></html>"
                    }
                };"##,
            "SSR",
            None,
            stdout.clone(),
        );

        let result_vector = stdout.lock().unwrap();

        assert_eq!(result, Ok("<html></html>".to_string()));
        assert_eq!(
            String::from_utf8_lossy(&result_vector),
            "  [SSR] [log] test log {\"answer\":42,\"nested\":{\"ready\":true}}\n"
        );
        assert_eq!(
            Ssr::render_console_line(
                "log",
                &[
                    ("test log".to_string(), false),
                    ("{\"answer\":42}".to_string(), true),
                ],
                true,
            ),
            "  \u{1b}[38;2;68;163;248m\u{1b}[1m[SSR]\u{1b}[0m \u{1b}[38;2;176;175;167m[log]\u{1b}[0m test log \u{1b}[38;2;190;190;184m{\"answer\":42}\u{1b}[0m"
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
