from __future__ import annotations

import shutil
from pathlib import Path

from nexui.io import NexUIError, read_text, write_text


PLACEHOLDERS = {
    "__TASK_ID__": "replace-me",
    "__TASK_TITLE__": "Replace Me",
    "__TASK_GOAL__": "Describe the goal for this task.",
    "__SOURCE_URL__": "https://example.com",
}


def copy_task_template(destination: str | Path, task_id: str) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    template_root = repo_root / "templates" / "task-template"
    destination_path = Path(destination).resolve()
    task_root = destination_path / task_id

    if task_root.exists():
        raise NexUIError(f"Task destination already exists: {task_root}")

    shutil.copytree(template_root, task_root)
    replacements = dict(PLACEHOLDERS)
    replacements["__TASK_ID__"] = task_id
    replacements["__TASK_TITLE__"] = task_id.replace("-", " ").title()

    for path in task_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in {".png"}:
            continue
        content = read_text(path)
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        write_text(path, content)

    return task_root
