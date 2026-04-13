import yaml
from pathlib import Path

_PROMPTS: dict | None = None


def load_prompts() -> dict:
    global _PROMPTS
    if _PROMPTS is None:
        path = Path(__file__).parent / "prompts.yaml"
        with open(path) as f:
            _PROMPTS = yaml.safe_load(f)
    return _PROMPTS


def get_prompt(name: str, part: str, **kwargs: object) -> str:
    prompts = load_prompts()
    template = prompts[name][part]
    if kwargs:
        return template.format(**kwargs)
    return template
