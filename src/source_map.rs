use lazy_static::lazy_static;
use path_absolutize::*;
use pyo3::prelude::*;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, PartialEq, Clone)]
#[pyclass(get_all, set_all)]
pub struct MapMetadata {
    line_number: i32,
    column_number: i32,
    source_index: Option<i32>,
    source_line: Option<i32>,
    source_column: Option<i32>,
    symbol_index: Option<i32>,
}

impl ToPyObject for MapMetadata {
    fn to_object(&self, py: Python) -> PyObject {
        self.clone().into_py(py)
    }
}

#[pymethods]
impl MapMetadata {
    #[new]
    fn new(line_number: i32, column_number: i32) -> Self {
        Self {
            line_number,
            column_number,
            source_index: None,
            source_line: None,
            source_column: None,
            symbol_index: None,
        }
    }
}

pub struct SourceMapParser {
    vlq_decoder: VLQDecoder,
}

impl SourceMapParser {
    pub fn new(vlq_decoder: VLQDecoder) -> Self {
        Self { vlq_decoder }
    }

    pub fn parse_mapping(
        &mut self,
        mappings: &str,
    ) -> Result<std::collections::HashMap<(i32, i32), MapMetadata>, String> {
        let mut parsed_mappings: std::collections::HashMap<(i32, i32), MapMetadata> =
            std::collections::HashMap::new();

        let mut metadata_state = MapMetadata::new(-1, -1);

        // Empty lines will have semi-colons next to one another
        for (line, encoded_metadata) in mappings.split(';').enumerate() {
            for component in encoded_metadata.split(',') {
                if component.trim().is_empty() {
                    continue;
                }

                let mut metadata = self.vlq_to_source_metadata(line as i32, component)?;
                metadata = self.merge_relative_metadatas(metadata, &mut metadata_state);

                parsed_mappings.insert(
                    // 1-index line numbers to match Javascript exception formatting
                    (metadata.line_number + 1, metadata.column_number + 1),
                    metadata,
                );
            }
        }

        Ok(parsed_mappings)
    }

    fn merge_relative_metadatas(
        &self,
        mut current_metadata: MapMetadata,
        metadata_state: &mut MapMetadata,
    ) -> MapMetadata {
        /*
         * The SourceMapParser spec defines all VLQ values as relative to the previous value. Some are
         * line dependent.
         *
         * Performs the merge in-place in the current_metadata and metadata_state objects, but returns
         * a reference to current_metadata for convenience.
         *
         * Note that the `metadata_state` isn't actually the previous instance of metadata, it should
         * be the rolling state of all non-None fields.
         */

        // Only column number is relative within the current line
        if metadata_state.line_number == current_metadata.line_number {
            current_metadata.column_number += metadata_state.column_number;
        }

        // Helper to merge and update attributes
        let merge_and_update_attribute = |current: &mut Option<i32>, state: &Option<i32>| {
            if let Some(current_val) = current {
                if let Some(state_val) = state {
                    *current = Some(*current_val + state_val);
                }
            }
        };

        // Merge attributes
        merge_and_update_attribute(
            &mut current_metadata.source_index,
            &metadata_state.source_index,
        );
        merge_and_update_attribute(
            &mut current_metadata.source_line,
            &metadata_state.source_line,
        );
        merge_and_update_attribute(
            &mut current_metadata.source_column,
            &metadata_state.source_column,
        );
        merge_and_update_attribute(
            &mut current_metadata.symbol_index,
            &metadata_state.symbol_index,
        );

        // Update state with non-None current values
        let update_state_attribute = |state: &mut Option<i32>, current: &Option<i32>| {
            if current.is_some() {
                *state = *current;
            }
        };

        metadata_state.line_number = current_metadata.line_number;
        metadata_state.column_number = current_metadata.column_number;

        update_state_attribute(
            &mut metadata_state.source_index,
            &current_metadata.source_index,
        );
        update_state_attribute(
            &mut metadata_state.source_line,
            &current_metadata.source_line,
        );
        update_state_attribute(
            &mut metadata_state.source_column,
            &current_metadata.source_column,
        );
        update_state_attribute(
            &mut metadata_state.symbol_index,
            &current_metadata.symbol_index,
        );

        current_metadata
    }

    fn vlq_to_source_metadata(&self, line: i32, component: &str) -> Result<MapMetadata, String> {
        let vlq_values = self.vlq_decoder.parse_vlq(component);

        match vlq_values.len() {
            1 => Ok(MapMetadata::new(line, vlq_values[0])),
            4 | 5 => {
                let mut metadata = MapMetadata::new(line, vlq_values[0]);
                metadata.source_index = Some(vlq_values[1]);
                metadata.source_line = Some(vlq_values[2]);
                metadata.source_column = Some(vlq_values[3]);
                if vlq_values.len() == 5 {
                    metadata.symbol_index = Some(vlq_values[4]);
                }
                Ok(metadata)
            }
            _ => Err(format!(
                "VLQ value should have 1, 4, or 5 components. Got {} instead: {:?}",
                vlq_values.len(),
                vlq_values
            )),
        }
    }
}

struct ValueMask {
    mask: u32,
    right_padding: u32,
}

pub struct VLQDecoder {
    alphabet: HashMap<char, u32>,
    sign_bit_mask: u32,
    continuation_bit_mask: u32,
    continuation_value_mask: ValueMask,
    original_value_mask: ValueMask,
}

impl VLQDecoder {
    pub fn new() -> Self {
        let alphabet = VLQDecoder::generate_base64_alphabet();
        Self {
            alphabet,
            sign_bit_mask: 0b1,
            continuation_bit_mask: 0b1 << 5,
            continuation_value_mask: ValueMask {
                mask: 0b011111,
                right_padding: 0,
            },
            original_value_mask: ValueMask {
                mask: 0b011110,
                right_padding: 1,
            },
        }
    }

    pub fn parse_vlq(&self, vlq_value: &str) -> Vec<i32> {
        let sextets: Vec<u32> = vlq_value
            .chars()
            .map(|c| *self.alphabet.get(&c).unwrap())
            .collect();

        let mut final_values = Vec::new();
        let mut current_value = 0;
        let mut current_bit_offset = 0;
        let mut current_sign_value = 1;

        let mut is_continuation = false;

        for sextet in sextets {
            let value_mask = if !is_continuation {
                current_sign_value = if sextet & self.sign_bit_mask != 0 {
                    -1
                } else {
                    1
                };
                &self.original_value_mask
            } else {
                &self.continuation_value_mask
            };

            current_value +=
                ((sextet & value_mask.mask) >> value_mask.right_padding) << current_bit_offset;
            current_bit_offset += if is_continuation { 5 } else { 4 };
            is_continuation = sextet & self.continuation_bit_mask != 0;

            if !is_continuation {
                final_values.push(current_sign_value * current_value as i32);
                current_value = 0;
                current_bit_offset = 0;
                current_sign_value = 1;
            }
        }

        final_values
    }

    fn generate_base64_alphabet() -> HashMap<char, u32> {
        let mut alphabet = HashMap::new();
        let alpha_ranges = vec![('A', 'Z'), ('a', 'z'), ('0', '9')];

        for (start, end) in alpha_ranges {
            for i in start..=end {
                alphabet.insert(i, alphabet.len() as u32);
            }
        }

        alphabet.insert('+', alphabet.len() as u32);
        alphabet.insert('/', alphabet.len() as u32);

        alphabet
    }
}

impl Default for VLQDecoder {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Serialize, Deserialize, Debug)]
struct SourceMapSchema {
    version: i32,
    sources: Vec<String>,
    names: Vec<String>,
    mappings: String,
    #[serde(rename = "sourcesContent")]
    sources_content: Option<Vec<String>>,
    #[serde(rename = "sourceRoot")]
    source_root: Option<String>,
    file: Option<String>,
}

pub fn make_source_map_paths_absolute(
    contents: &str,
    original_script_path: &Path,
) -> serde_json::Result<String> {
    let mut source_map: SourceMapSchema = serde_json::from_str(contents)?;

    let parent_path = original_script_path
        .parent()
        .unwrap_or_else(|| Path::new(""));

    source_map.sources = source_map
        .sources
        .iter()
        .map(|source| {
            let source_path = Path::new(source);
            if source_path.is_absolute() {
                source_path.absolutize().unwrap().to_path_buf()
            } else {
                parent_path
                    .join(source_path)
                    .absolutize()
                    .unwrap()
                    .to_path_buf()
            }
        })
        .map(|path| path.to_string_lossy().into_owned())
        .collect();

    serde_json::to_string(&source_map)
}

pub fn update_source_map_path(contents: &str, new_path: &str) -> String {
    lazy_static! {
        static ref RE: Regex =
            Regex::new(r"sourceMappingURL=(.*?).map").expect("Failed to compile regex");
    }

    RE.replace_all(
        contents,
        format!("sourceMappingURL={}.map", new_path).as_str(),
    )
    .into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn test_vlq_constants() {
        let decoder = VLQDecoder::new();
        assert_eq!(decoder.alphabet.len(), 64);
        assert_eq!(decoder.sign_bit_mask, 0b000001);
        assert_eq!(decoder.continuation_bit_mask, 0b100000);
    }

    #[test]
    fn test_parse_vlq() {
        let test_cases = vec![
            ("aAYQA", vec![13, 0, 12, 8, 0]),
            ("CAAA", vec![1, 0, 0, 0]),
            ("SAAAA", vec![9, 0, 0, 0, 0]),
            ("GAAA", vec![3, 0, 0, 0]),
            ("mCAAmC", vec![35, 0, 0, 35]),
            ("kBAChO", vec![18, 0, 1, -224]),
            ("AClrFA", vec![0, 1, -2738, 0]),
        ];

        let decoder = VLQDecoder::new();

        for (encoded, expected) in test_cases {
            assert_eq!(decoder.parse_vlq(encoded), expected);
        }
    }

    #[derive(Debug, PartialEq, Clone)]
    struct MergeMetadataTestCase {
        metadata_state: MapMetadata,
        current_metadata: MapMetadata,
        expected_metadata: MapMetadata,
        expected_metadata_state: MapMetadata,
    }

    #[test]
    fn test_merge_metadatas() {
        let test_cases = vec![
            // Simple merge of relative values, same line
            MergeMetadataTestCase {
                metadata_state: MapMetadata {
                    line_number: 1,
                    column_number: 10,
                    source_index: Some(10),
                    source_line: Some(10),
                    source_column: Some(10),
                    symbol_index: Some(10),
                },
                current_metadata: MapMetadata {
                    line_number: 1,
                    column_number: 20,
                    source_index: Some(20),
                    source_line: Some(20),
                    source_column: Some(20),
                    symbol_index: Some(20),
                },
                expected_metadata: MapMetadata {
                    line_number: 1,
                    column_number: 30,
                    source_index: Some(30),
                    source_line: Some(30),
                    source_column: Some(30),
                    symbol_index: Some(30),
                },
                expected_metadata_state: MapMetadata {
                    line_number: 1,
                    column_number: 30,
                    source_index: Some(30),
                    source_line: Some(30),
                    source_column: Some(30),
                    symbol_index: Some(30),
                },
            },
            // Merge of values on a different line, should reset
            // the column number but leave everything else relative
            MergeMetadataTestCase {
                metadata_state: MapMetadata {
                    line_number: 1,
                    column_number: 10,
                    source_index: Some(10),
                    source_line: Some(10),
                    source_column: Some(10),
                    symbol_index: Some(10),
                },
                current_metadata: MapMetadata {
                    line_number: 2,
                    column_number: 20,
                    source_index: Some(20),
                    source_line: Some(20),
                    source_column: Some(20),
                    symbol_index: Some(20),
                },
                expected_metadata: MapMetadata {
                    line_number: 2,
                    column_number: 20,
                    source_index: Some(30),
                    source_line: Some(30),
                    source_column: Some(30),
                    symbol_index: Some(30),
                },
                expected_metadata_state: MapMetadata {
                    line_number: 2,
                    column_number: 20,
                    source_index: Some(30),
                    source_line: Some(30),
                    source_column: Some(30),
                    symbol_index: Some(30),
                },
            },
        ];

        for case in test_cases {
            let parser = SourceMapParser::new(VLQDecoder::new());
            let mut metadata_state = case.metadata_state.clone();
            let current_metadata = case.current_metadata;
            let result_metadata =
                parser.merge_relative_metadatas(current_metadata, &mut metadata_state);

            assert_eq!(
                result_metadata, case.expected_metadata,
                "Failed test for expected_metadata"
            );
            assert_eq!(
                metadata_state, case.expected_metadata_state,
                "Failed test for expected_metadata_state"
            );
        }
    }

    #[test]
    fn test_make_source_map_paths_absolute() {
        let temp_dir = tempdir().unwrap();
        let temp_dir_path = temp_dir.path();
        let original_script_path = temp_dir_path.join("dist/main.js");
        fs::create_dir_all(original_script_path.parent().unwrap()).unwrap();

        // Paths are relative to the output file
        let contents = r#"{
            "version": 3,
            "sources": ["./src/file1.js", "/absolute/path/../path/src/file2.js"],
            "names": [],
            "mappings": "",
            "sourcesContent": null,
            "sourceRoot": null,
            "file": null
        }"#;

        // Expected result - we make sure to also absolutize this path to make it compatible
        // with both windows and OSX path separators. On windows it will convert the slash to \\
        let expected_relative: &str;
        let expected_absolute: &str;

        #[cfg(target_os = "windows")]
        {
            expected_relative = "dist\\src\\file1.js";
            expected_absolute = "C:\\absolute\\path\\src\\file2.js";
        }

        #[cfg(not(target_os = "windows"))]
        {
            expected_relative = "dist/src/file1.js";
            expected_absolute = "/absolute/path/src/file2.js";
        }

        let expected_source_1 = temp_dir_path
            .join(expected_relative)
            .to_string_lossy()
            .into_owned();
        let expected_source_2 = Path::new(expected_absolute).to_string_lossy().into_owned();

        let modified_json =
            make_source_map_paths_absolute(contents, &original_script_path).unwrap();
        let modified_source_map: SourceMapSchema = serde_json::from_str(&modified_json).unwrap();

        // Verify the results
        assert_eq!(modified_source_map.sources[0], expected_source_1);
        assert_eq!(modified_source_map.sources[1], expected_source_2);
    }

    #[test]
    fn test_update_source_map_path() {
        let test_cases = vec![
            // Single, simple replacement
            (
                "var testing; //# sourceMappingURL=myfile.js.map",
                "final_path.js",
                "var testing; //# sourceMappingURL=final_path.js.map",
            ),
            // Multiple replacements
            (
                "var testing; //# sourceMappingURL=first.js.map //# sourceMappingURL=second.js.map",
                "final_path.js",
                "var testing; //# sourceMappingURL=final_path.js.map //# sourceMappingURL=final_path.js.map",
            ),
        ];

        for (input_str, replace_path, expected_output) in test_cases {
            assert_eq!(
                update_source_map_path(input_str, replace_path),
                expected_output
            );
        }
    }
}
