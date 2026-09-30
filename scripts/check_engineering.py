"""Validate project agent configuration, skill discovery, and local doc links."""

import re
import sys
import tomllib
from pathlib import Path

import yaml

ROLES = frozenset({"research", "code", "design", "debug", "review", "usage"})
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultra"})


def validate(root: Path) -> list[str]:
    """Return wiring errors without modifying files or calling models."""
    errors = []
    configs = root / ".codex/agents"
    skills = root / ".agents/skills"
    if {p.stem for p in configs.glob("*.toml")} != ROLES:
        errors.append("Agent configs must define exactly the six project roles.")
    if {p.parent.name for p in skills.glob("*/SKILL.md")} != ROLES:
        errors.append("Skills must define exactly the six project procedures.")
    for role in sorted(ROLES):
        config_path = configs / f"{role}.toml"
        skill_path = skills / role / "SKILL.md"
        try:
            config = tomllib.loads(config_path.read_text())
            if config.get("name") != role:
                errors.append(f"{role}: agent name must match its filename")
            for key in ("description", "developer_instructions", "model"):
                if not isinstance(config.get(key), str) or not config[key].strip():
                    errors.append(f"{role}: missing {key}")
            if config.get("model_reasoning_effort") not in EFFORTS:
                errors.append(f"{role}: unsupported reasoning effort")
            if f".agents/skills/{role}/SKILL.md" not in config.get("developer_instructions", ""):
                errors.append(f"{role}: instructions do not route to its skill")
            if config.get("sandbox_mode") not in {"read-only", "workspace-write"}:
                errors.append(f"{role}: unexpected sandbox setting")
            if role in {"research", "design", "review"} and config.get("sandbox_mode") != "read-only":
                errors.append(f"{role}: expected read-only role")
            content = skill_path.read_text()
            match = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
            if not match:
                errors.append(f"{role}: missing skill frontmatter")
                continue
            meta = yaml.safe_load(match.group(1))
            if not isinstance(meta, dict) or meta.get("name") != role:
                errors.append(f"{role}: skill name must match its directory")
                continue
            if not isinstance(meta.get("description"), str) or not meta["description"].strip():
                errors.append(f"{role}: missing skill description")
            if "model" in meta or "model_reasoning_effort" in meta:
                errors.append(f"{role}: model selection belongs in the agent config")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{role}: {exc}")
    try:
        global_config = tomllib.loads((root / ".codex/config.toml").read_text())
        agents = global_config["agents"]
        if agents.get("enabled") is not True:
            errors.append("Project agents must be enabled.")
        limit = agents.get("max_concurrent_threads_per_session")
        if type(limit) is not int or limit < 1:
            errors.append("Agent concurrency must be a positive integer.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"Project config: {exc}")
    documents = [*skills.rglob("*.md")]
    documents += [root / "docs" / name for name in ("architecture.md", "engineering.md", "task-template.md")]
    for document in documents:
        try:
            content = document.read_text()
        except OSError as exc:
            errors.append(str(exc))
            continue
        for target in re.findall(r"\]\(([^)]+)\)", content):
            if "://" in target or target.startswith("#"):
                continue
            path = (document.parent / target.split("#", 1)[0]).resolve()
            if not path.is_relative_to(root.resolve()) or not path.exists():
                errors.append(f"{document.relative_to(root)}: broken local link {target}")
    return errors


def main() -> int:
    """Report wiring errors; success does not certify model access or agent behavior."""
    errors = validate(Path(__file__).resolve().parents[1])
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("PASS: six agent configs, skill metadata, routing, and local doc links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
