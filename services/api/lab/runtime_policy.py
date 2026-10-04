"""Read the configured runtime policy at the request boundary."""

from pathlib import Path

from lab.errors import RuntimePolicyUnavailable


def load_runtime_policy(path: Path) -> str:
    """Return the complete UTF-8 policy or raise a content-safe domain error."""
    try:
        policy = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimePolicyUnavailable(
            "The Learning Lab runtime policy is unavailable. Restore the configured policy file and retry."
        ) from exc
    if not policy.strip():
        raise RuntimePolicyUnavailable("The Learning Lab runtime policy is empty. Restore its contents and retry.")
    return policy
