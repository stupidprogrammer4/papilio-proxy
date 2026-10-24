"""Native Go module metadata uses a stream of separate JSON objects."""

import pytest
from deployment.papilio_installer.node.notices import json_objects


def test_module_metadata_retains_each_explicit_module_identity() -> None:
    result = json_objects(' {"Path":"first","Version":"v1"}\n{"Path":"second","Version":"v2"}\n')
    assert result == ({"Path": "first", "Version": "v1"}, {"Path": "second", "Version": "v2"})


@pytest.mark.parametrize("value", ["[]", "null", '{"Path":"first"}\ninvalid'])
def test_nonobject_or_invalid_module_metadata_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        json_objects(value)
