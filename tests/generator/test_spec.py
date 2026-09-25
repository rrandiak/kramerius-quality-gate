# Spec parsing: shipped specs load, bad knobs fail loudly at the boundary.

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from qg.generator.spec import Spec, load_spec

from .conftest import SPECS


@pytest.mark.parametrize("name", ["tiny.yaml", "mzk-like.yaml"])
def test_shipped_specs_load(name: str) -> None:
    spec = load_spec(SPECS / name)

    assert spec.models.page_shares()


def test_digest_is_stable_and_distinguishes_specs(tiny_spec: Spec) -> None:
    again = load_spec(SPECS / "tiny.yaml")
    other = load_spec(SPECS / "mzk-like.yaml")

    assert tiny_spec.digest() == again.digest()
    assert tiny_spec.digest() != other.digest()


def _tiny_raw() -> dict[str, object]:
    raw: dict[str, object] = yaml.safe_load((SPECS / "tiny.yaml").read_text())
    return raw


def test_unknown_paper_size_is_rejected() -> None:
    raw = _tiny_raw()
    raw["pages"]["paper_sizes"] = {"Letter": 1.0}  # type: ignore[index]

    with pytest.raises(ValidationError, match="unknown paper sizes"):
        Spec.model_validate(raw)


def test_volume_pages_required_when_volumes_can_own_pages() -> None:
    raw = _tiny_raw()
    del raw["models"]["periodical"]["profiles"]["monthly"]["volume_pages"]  # type: ignore[index]

    with pytest.raises(ValidationError, match="volume_pages is required"):
        Spec.model_validate(raw)


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    raw = _tiny_raw()
    raw["colour"] = "blue"

    with pytest.raises(ValidationError, match="colour"):
        Spec.model_validate(raw)
