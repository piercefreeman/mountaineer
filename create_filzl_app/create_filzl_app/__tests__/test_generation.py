from create_filzl_app.generation import ProjectMetadata, format_template


def test_path_url_replacement():
    metadata = ProjectMetadata(
        project_name="TEST_PROJECT_NAME",
        author="TEST_AUTHOR",
        use_tailwind=True,
        use_poetry=True,
    )
    bundle = format_template("[project_name]/app.py", metadata)
    assert bundle.path == "TEST_PROJECT_NAME/app.py"
