"""Contract checks for the repository's architecture diagrams."""

from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIAGRAMS = (ROOT / "docs/architecture.svg", ROOT / "docs/task-lifecycle.svg")
SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"
ALLOWED_COLORS = {"black", "white", "#000", "#fff", "#000000", "#ffffff"}


def _assert_contract(path: Path) -> None:
    root = ElementTree.parse(path).getroot()
    assert root.tag == f"{SVG_NAMESPACE}svg"

    title = root.find(f"{SVG_NAMESPACE}title")
    description = root.find(f"{SVG_NAMESPACE}desc")
    assert title is not None and (title.text or "").strip()
    assert description is not None and (description.text or "").strip()

    text = " ".join((node.text or "") for node in root.iter(f"{SVG_NAMESPACE}text"))
    assert len(text.split()) >= 10

    for element in root.iter():
        for attribute, value in element.attrib.items():
            if attribute in {"href", "src"}:
                assert value.startswith("#"), f"external asset reference: {value}"
            if attribute in {"fill", "stroke", "stop-color", "color"}:
                assert value.lower() in ALLOWED_COLORS or value.lower() == "none"

    for style in root.iter(f"{SVG_NAMESPACE}style"):
        assert style.text
        for declaration in style.text.split("{")[1:]:
            properties = declaration.split("}", maxsplit=1)[0].split(";")
            for property_value in properties:
                if ":" not in property_value:
                    continue
                name, value = property_value.split(":", maxsplit=1)
                if name.strip() in {"fill", "stroke", "color", "stop-color"}:
                    color = value.strip().lower()
                    assert color in ALLOWED_COLORS or color == "none"
        assert "url(http" not in style.text.lower()

    serialized = ElementTree.tostring(root, encoding="unicode").lower()
    assert "http://" not in serialized.replace(
        'xmlns:ns0="http://www.w3.org/2000/svg"', ""
    )
    assert "https://" not in serialized
    assert "<image" not in serialized
    assert "<script" not in serialized
    assert "@font-face" not in serialized
    assert "font-family: url(" not in serialized


@pytest.mark.parametrize("path", DIAGRAMS, ids=lambda path: path.name)
def test_diagrams_are_accessible_monochrome_svg(path: Path) -> None:
    _assert_contract(path)


def test_rejects_external_assets_and_non_monochrome_colors() -> None:
    invalid_svg = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <title>Invalid sample</title>
  <desc>External image and color are forbidden.</desc>
  <rect fill="#f00" href="https://example.test/image.svg"/>
</svg>
"""
    root = ElementTree.fromstring(invalid_svg)

    with pytest.raises(AssertionError):
        for element in root.iter():
            for attribute, value in element.attrib.items():
                if attribute in {"href", "src"}:
                    assert value.startswith("#"), f"external asset reference: {value}"
                if attribute in {"fill", "stroke", "stop-color", "color"}:
                    assert value.lower() in ALLOWED_COLORS or value.lower() == "none"
