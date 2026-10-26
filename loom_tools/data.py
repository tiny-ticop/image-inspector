from pathlib import Path


def grouped_images(root, extensions):
    root=Path(root).resolve()
    if not root.is_dir():raise ValueError(f'Input directory not found: {root}')
    paths={}
    for machine in sorted(p for p in root.iterdir() if p.is_dir()):
        delay=machine/'delay'
        if not delay.is_dir():continue
        for angle in sorted((p for p in delay.iterdir() if p.is_dir() and p.name.isdigit()),key=lambda p:int(p.name)):
            for image in sorted(p for p in angle.iterdir() if p.is_file() and p.suffix.lower() in extensions):
                if not image.resolve().is_relative_to(root):continue
                key=image.relative_to(root).with_suffix('').as_posix()
                if key in paths:raise ValueError(f'Ambiguous image basename: {key}')
                paths[key]=image
    return paths
