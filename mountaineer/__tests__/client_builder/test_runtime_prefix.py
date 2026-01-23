from mountaineer.static import get_static_path


def test_api_root_path_prefixing():
    api_contents = get_static_path("api.ts").read_text()
    assert "__MOUNTAINEER_ROOT_PATH" in api_contents
    assert "withRootPath" in api_contents
    assert "new ServerURL(withRootPath" in api_contents
