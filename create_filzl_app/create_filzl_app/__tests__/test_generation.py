from create_filzl_app.generation import ProjectMetadata, format_template


def test_path_url_replacement():
    metadata = ProjectMetadata(
        project_name="TEST_PROJECT_NAME",
        author="TEST_AUTHOR",
        use_tailwind=True,
    )
    _, output_path = format_template("[project_name]/app.py", metadata)
    assert output_path == "TEST_PROJECT_NAME/app.py"
