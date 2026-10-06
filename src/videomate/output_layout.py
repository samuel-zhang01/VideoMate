"""Output layout is local only. Sensitive jobs always use neutral names."""
from pathlib import Path

from .errors import VideoMateError
from .policy import plain_local_path

LAYOUTS = ("neutral", "filename", "folders")


def plan_layout(inputs, paths, layout, sensitive):
    if layout not in LAYOUTS:
        raise VideoMateError("invalid_arguments")
    if sensitive:
        return {}
    if layout == "neutral":
        return {}
    roots = [plain_local_path(Path(p).absolute()) for p in inputs]
    roots = [p if p.is_dir() else p.parent for p in roots]
    # Independent selections have separate roots; never mirror a whole drive or
    # infer a common user-profile ancestor. Nested selections choose the deepest.
    unique = list(dict.fromkeys(roots))
    result = {}
    for number, source in enumerate(paths, 1):
        if layout == "filename":
            relative = Path(source.name)
        else:
            matches = [p for p in unique if source == p or p in source.parents]
            if not matches:
                raise VideoMateError("input_rejected")
            root = max(matches, key=lambda p: len(p.parts))
            relative = source.relative_to(root)
            if len(unique) > 1:
                relative = Path("selection-" + str(unique.index(root) + 1)) / relative
        if relative.is_absolute() or ".." in relative.parts:
            raise VideoMateError("input_rejected")
        result[str(number)] = str(relative)
    return result


def destination_root(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or relative.name in {"", ".", ".."}:
        raise VideoMateError("input_rejected")
    target = plain_local_path(root / relative)
    if root not in target.parents:
        raise VideoMateError("input_rejected")
    return target.parent, target.stem
