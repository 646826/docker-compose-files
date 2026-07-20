#!/usr/bin/env python3
from pathlib import Path

path = Path("scripts/backup.py")
text = path.read_text(encoding="utf-8")
old = '''    created: list[str] = []
    current_name: str | None = None
    current_preexisting = False
    try:
        for logical, name, _archive, existed in plan:
            if not existed:
                docker.create_volume(name, project, logical)
                created.append(name)
        for _logical, name, archive, existed in plan:
            current_name = name
            current_preexisting = existed
            docker.stream_restore(archive, name)
        return [name for _logical, name, _archive, _existed in plan]
    except Exception as exc:
        cleanup_errors: list[str] = []
        for name in reversed(created):
            try:
                docker.remove_volume(name)
            except Exception as cleanup_exc:  # pragma: no cover - real Docker diagnostic path
                cleanup_errors.append(f"{name}: {cleanup_exc}")
        detail = str(exc)
        if current_name is not None and current_preexisting:
            detail += f"; pre-existing volume {current_name} may be partially populated"
        if cleanup_errors:
            detail += f"; cleanup failures: {', '.join(cleanup_errors)}"
'''
new = '''    created: list[str] = []
    touched_preexisting: list[str] = []
    try:
        for logical, name, _archive, existed in plan:
            if not existed:
                docker.create_volume(name, project, logical)
                created.append(name)
        for _logical, name, archive, existed in plan:
            if existed:
                touched_preexisting.append(name)
            docker.stream_restore(archive, name)
        return [name for _logical, name, _archive, _existed in plan]
    except Exception as exc:
        cleanup_errors: list[str] = []
        for name in reversed(created):
            try:
                docker.remove_volume(name)
            except Exception as cleanup_exc:  # pragma: no cover - real Docker diagnostic path
                cleanup_errors.append(f"{name}: {cleanup_exc}")
        detail = str(exc)
        if touched_preexisting:
            detail += "; pre-existing volumes may be partially populated: " + ", ".join(
                touched_preexisting
            )
        if cleanup_errors:
            detail += f"; cleanup failures: {', '.join(cleanup_errors)}"
'''
if text.count(old) != 1:
    raise SystemExit("expected restore error-handling block was not found exactly once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
