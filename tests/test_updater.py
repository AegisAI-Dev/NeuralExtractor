from neural_extractor_v3.core.updater import UpdateChecker, is_newer_version, version_tuple


def test_version_tuple_handles_tags():
    assert version_tuple("v3.2.10") == (3, 2, 10)
    assert version_tuple("release-4") == (4,)
    assert version_tuple("not-a-version") == (0,)


def test_is_newer_version_pads_versions():
    assert is_newer_version("v3.0.1", "3.0.0")
    assert not is_newer_version("v3.0.0", "3.0")
    assert not is_newer_version("v2.9.9", "3.0.0")


def test_parse_release_selects_v3_exe_asset():
    payload = {
        "tag_name": "v3.1.0",
        "name": "Neural Extractor V3 v3.1.0",
        "html_url": "https://example.test/releases/v3.1.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "notes.txt",
                "browser_download_url": "https://example.test/notes.txt",
            },
            {
                "name": "NeuralExtractorV3.exe",
                "browser_download_url": "https://example.test/NeuralExtractorV3.exe",
            },
        ],
    }

    info = UpdateChecker(api_url="https://example.test").parse_release(payload, "3.0.0")

    assert info is not None
    assert info.version == "3.1.0"
    assert info.download_url == "https://example.test/NeuralExtractorV3.exe"


def test_parse_release_ignores_old_release():
    payload = {"tag_name": "v2.9.0", "draft": False, "prerelease": False}

    assert UpdateChecker(api_url="https://example.test").parse_release(payload, "3.0.0") is None
