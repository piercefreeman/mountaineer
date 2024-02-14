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
use std::collections::HashMap;

#[derive(Clone, Debug, PartialEq)]
pub struct Ssr<'a> {
    // TODO: Check if better Box<str> instead of String
    source: String,
    entry_point: &'a str,
}

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
        Self::render(self.source.clone(), self.entry_point, params)
    }

    fn render(source: String, entry_point: &str, params: Option<&str>) -> Result<String, AppError> {
        /*
         * Main entrypoint for rendering, takes a source string (containing one or many functions) and
         * an entry point (ie. function name to execute) and returns the result of the execution as
         * a string.
         */
        // let isolate_params = v8::CreateParams::default().heap_limits(0, 2000 * 1024 * 1024);
        let isolate = &mut v8::Isolate::new(Default::default());
        let handle_scope = &mut v8::HandleScope::new(isolate);
        let context = v8::Context::new(handle_scope);
        let scope = &mut v8::ContextScope::new(handle_scope, context);

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
            let maybe_stack = exceptions.map_or_else(
                || String::new(),
                |trace| format!("\nStack: {}", trace.to_rust_string_lossy(&mut scope)),
            );

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

#[cfg(test)]
mod tests {
    use super::*;

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
}
