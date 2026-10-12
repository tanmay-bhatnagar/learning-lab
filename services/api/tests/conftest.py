import pytest


@pytest.fixture(autouse=True)
def isolated_runtime_policy(tmp_path_factory):
    """Keep API tests independent of the personal runtime-policy file."""
    policy_path = tmp_path_factory.mktemp("runtime-policy") / "runtime-policy.md"
    policy_path.write_text("Synthetic test runtime policy.", encoding="utf-8")
    with pytest.MonkeyPatch.context() as isolated_env:
        isolated_env.setenv("LEARNING_LAB_POLICY_PATH", str(policy_path))
        isolated_env.setenv("LEARNING_LAB_PROFILE_ROOT", str(tmp_path_factory.mktemp("profile")))
        yield


@pytest.fixture
def parser_map_factory():
    def _factory(fn):
        return {"markitdown": fn, "anydoc": fn}

    return _factory
