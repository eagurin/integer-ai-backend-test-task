"""Машинно-проверяемые ссылки и команды README."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"


def _relative_links(readme: str) -> list[Path]:
    """Разобрать относительные Markdown-ссылки README в пути."""
    links = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", readme)
    return [
        (ROOT / target.split("#", maxsplit=1)[0]).resolve()
        for target in links
        if "://" not in target and not target.startswith("#")
    ]


def _fenced_commands(readme: str) -> list[str]:
    """Вернуть строки shell-блоков без пустых строк и комментариев."""
    return [
        line.strip()
        for block in re.findall(r"```bash\n(.*?)```", readme, re.DOTALL)
        for line in block.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _assert_relative_links_exist(readme: str) -> None:
    """Reject a README containing a broken relative link."""
    broken_links = [path for path in _relative_links(readme) if not path.is_file()]
    assert not broken_links, f"Broken README links: {broken_links}"


def test_readme_relative_asset_links_resolve() -> None:
    """Given README assets, when links are parsed, then all paths exist."""
    readme = README.read_text()
    links = _relative_links(readme)
    assert links
    _assert_relative_links_exist(readme)
    assert {path.name for path in links} >= {
        "architecture.svg",
        "task-lifecycle.svg",
    }


def test_readme_commands_target_real_project_operations() -> None:
    """Given documented shell commands, then targets match project config."""
    readme = README.read_text()
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert "tests" in compose["services"]
    assert '"ruff>=' in pyproject and '"mypy>=' in pyproject

    commands = _fenced_commands(readme)
    assert "docker compose up --build -d" in commands
    assert "docker compose --profile test run --rm tests uv run pytest -q" in commands
    assert (
        "docker compose --profile test run --rm tests uv run ruff check ." in commands
    )
    assert (
        "docker compose --profile test run --rm tests uv run ruff format --check ."
        in commands
    )
    assert "docker compose --profile test run --rm tests uv run mypy ." in commands
    assert any("alembic upgrade head" in command for command in commands)
    assert any("alembic revision --autogenerate" in command for command in commands)
    assert (ROOT / "scripts/smoke.py").is_file()


def test_rejects_broken_relative_asset_link() -> None:
    """Given a missing local asset, when validating links, then reject it."""
    broken_readme = "![missing](docs/missing-diagram.svg)"
    try:
        _assert_relative_links_exist(broken_readme)
    except AssertionError:
        return
    raise AssertionError("Broken README asset link was accepted")
