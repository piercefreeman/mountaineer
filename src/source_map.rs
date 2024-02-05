use pyo3::prelude::*;
use std::collections::HashMap;

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
        self.clone().into_py(py).into()
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

#[cfg(test)]
mod tests {
    use super::*;

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
}
