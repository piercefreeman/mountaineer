use tree_sitter::TreeCursor;

pub fn find_use_server_instances(cursor: &mut TreeCursor, code: &str, instances: &mut Vec<String>) {
    /*
     * The useServer() init functions are the main entrypoints for the serverside injection of
     * variables into the client runtime. These are synthetic functions that will be filled in
     * by the server when results are dynamically generated.
     */
    loop {
        let node = cursor.node();
        println!(
            "Visiting node: {} [{}]",
            node.kind(),
            code[node.start_byte()..node.end_byte()].trim()
        );

        if node.kind() == "function_body" || node.kind() == "arrow_function" {
            cursor.goto_first_child();
        }

        if node.kind() == "variable_declarator" {
            // Get first child
            // Check whether it's an identifier
            // Then, check whether the call_expression is the second child
            let mut child_cursor = node.walk();

            if child_cursor.goto_first_child() {
                let identifier = child_cursor.node();
                if identifier.kind() == "identifier" {
                    let identifier_name =
                        code[identifier.start_byte()..identifier.end_byte()].trim();
                    println!("Found identifier: {}", identifier_name);

                    if child_cursor.goto_next_sibling() {
                        if child_cursor.node().kind() == "=" {
                            if child_cursor.goto_next_sibling() {
                                // Expected variable assignment
                                let call_expression = child_cursor.node();
                                println!("NEXT SIBLING: {}", call_expression.kind());
                                if call_expression.kind() == "call_expression" {
                                    // Here, check if the call_expression meets your criteria
                                    // For example, if it's a call to `useServer()`
                                    // Then, you can add `identifier_name` to `instances`
                                    let function_name = get_call_function(&mut child_cursor, code);
                                    println!(
                                        "Found call expression: {} {} {:?}",
                                        &code[call_expression.start_byte()
                                            ..call_expression.end_byte()],
                                        identifier_name,
                                        function_name
                                    );
                                    if function_name == Some("useServer".to_string()) {
                                        instances.push(identifier_name.to_string());
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        if !cursor.goto_first_child() {
            while !cursor.goto_next_sibling() {
                if !cursor.goto_parent() {
                    return;
                }
            }
        }
    }
}

pub fn collect_properties(
    cursor: &mut TreeCursor,
    code: &str,
    instance: &String,
    results: &mut Vec<String>,
) {
    loop {
        let node = cursor.node();

        if node.kind() == "function_body" || node.kind() == "arrow_function" {
            cursor.goto_first_child();
        }

        if node.kind() == "member_expression" {
            let expression_text = code[node.start_byte()..node.end_byte()].trim().to_string();
            println!("Found member expression: {} {}", expression_text, instance);
            if expression_text.starts_with(instance) {
                results.push(expression_text);
            }
        }

        if !cursor.goto_first_child() {
            while !cursor.goto_next_sibling() {
                if !cursor.goto_parent() {
                    return;
                }
            }
        }
    }
}

fn get_call_function(cursor: &mut TreeCursor, code: &str) -> Option<String> {
    let node = cursor.node();

    if node.kind() == "call_expression" {
        let mut child_cursor = node.walk();
        if child_cursor.goto_first_child() {
            match child_cursor.node().kind() {
                "identifier" => Some(
                    child_cursor
                        .node()
                        .utf8_text(code.as_bytes())
                        .unwrap()
                        .to_string(),
                ),
                "member_expression" => get_member_expression_name(&mut child_cursor, code),
                _ => None,
            }
        } else {
            None
        }
    } else {
        None
    }
}

fn get_member_expression_name(cursor: &mut TreeCursor, code: &str) -> Option<String> {
    let node = cursor.node();

    if node.kind() == "member_expression" && cursor.goto_first_child() {
        match cursor.node().kind() {
            "identifier" => Some(
                cursor
                    .node()
                    .utf8_text(code.as_bytes())
                    .unwrap()
                    .to_string(),
            ),
            _ => None,
        }
    } else {
        None
    }
}
