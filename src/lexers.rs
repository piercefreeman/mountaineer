pub fn strip_js_comments(js_string: &str, skip_whitespace: bool) -> String {
    let mut final_text = String::new();
    let chars: Vec<char> = js_string.chars().collect();
    let mut i = 0;
    let mut is_in_block_comment = false;
    let mut is_in_line_comment = false;
    // Track the current string delimiter (None if not in a string)
    let mut string_delimiter: Option<char> = None;

    while i < chars.len() {
        match chars[i] {
            // Handle strings
            '"' | '\'' | '`'
                if !is_in_block_comment && !is_in_line_comment && string_delimiter.is_none() =>
            {
                // Entering a string
                string_delimiter = Some(chars[i]);
                final_text.push(chars[i]);
            }
            ch if Some(ch) == string_delimiter && i > 0 && chars[i - 1] != '\\' => {
                // Exiting a string
                string_delimiter = None;
                final_text.push(chars[i]);
            }
            // Handle comments
            '/' if (i == 0 || chars[i - 1] != '\\')
                && string_delimiter.is_none()
                && i + 1 < chars.len() =>
            {
                match chars[i + 1] {
                    '/' => {
                        // Double slashes can be nested in a block comment and should be treated
                        // just like a regular string, they will end when the block comment does
                        // and not when the line does
                        if !is_in_block_comment {
                            is_in_line_comment = true;
                        }
                        i += 1; // Skip next char as it's part of the comment syntax
                    }
                    '*' => {
                        is_in_block_comment = true;
                        i += 1; // Skip next char as it's part of the comment syntax
                    }
                    _ => final_text.push(chars[i]),
                }
            }
            '*' if is_in_block_comment && i + 1 < chars.len() => {
                match chars[i + 1] {
                    '/' => {
                        is_in_block_comment = false;
                        i += 1; // Skip next char as it's part of the comment syntax
                    }
                    _ => final_text.push(chars[i]),
                }
            }
            '\n' if is_in_line_comment => {
                is_in_line_comment = false;
            }
            // Skip over all whitespaces outside of strings
            ch if ch.is_whitespace() && skip_whitespace && string_delimiter.is_none() => (),
            // Fallback for normal non-comment characters
            _ if !is_in_block_comment && !is_in_line_comment => {
                final_text.push(chars[i]);
            }
            _ => (),
        }

        i += 1;
    }

    final_text
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strip_js_comments() {
        let test_cases = vec![
            ("", ""),
            ("let x = 5; // This is a line comment", "let x = 5; "),
            (
                "let x = 5; /* This is a block comment */ let y = 10;",
                "let x = 5;  let y = 10;",
            ),
            (
                "let x = \"// This is not a comment\";",
                "let x = \"// This is not a comment\";",
            ),
            ("// Comment 1\n// Comment 2\nlet x = 5;", "let x = 5;"),
            (
                "let x = 5; / Incomplete comment syntax",
                "let x = 5; / Incomplete comment syntax",
            ),
            (
                "let x = 5; // Line comment\nlet y = 10; /* Block comment */ let z = 15;",
                "let x = 5; let y = 10;  let z = 15;",
            ),
            (
                "let x = \"String with \\\\\"//fake comment\\\\\" inside\";",
                "let x = \"String with \\\\\"//fake comment\\\\\" inside\";",
            ),
            (
                "// Comment at start\nlet x = 5;\n// Comment at end",
                "let x = 5;\n",
            ),
        ];

        for (input, expected) in test_cases {
            assert_eq!(
                strip_js_comments(&String::from(input), false),
                String::from(expected)
            );
        }
    }

    #[test]
    fn test_strip_js_comments_skip_whitespace() {
        let test_cases = vec![("let x = 5; // This is a line comment", "letx=5;")];

        for (input, expected) in test_cases {
            assert_eq!(
                strip_js_comments(&String::from(input), true),
                String::from(expected)
            );
        }
    }
}
