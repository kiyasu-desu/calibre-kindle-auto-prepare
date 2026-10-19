"""Build the installable Calibre ZIP from an explicit file allowlist."""
import argparse
import ast
import os
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_FILES = (
    "__init__.py",
    "config.py",
    "core.py",
    "plugin-import-name-kindle_auto_prepare.txt",
)


def read_version(root=ROOT):
    tree = ast.parse((Path(root) / "plugin" / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "KindleAutoPrepare":
            for assignment in node.body:
                if isinstance(assignment, ast.Assign):
                    if any(isinstance(target, ast.Name) and target.id == "version"
                           for target in assignment.targets):
                        version = ast.literal_eval(assignment.value)
                        if (isinstance(version, tuple) and len(version) == 3
                                and all(type(part) is int and part >= 0 for part in version)):
                            return ".".join(map(str, version))
    raise ValueError("Cannot find the plugin's three-part version.")


def build_plugin(root=ROOT, destination=None):
    root = Path(root)
    version = read_version(root)
    destination = Path(destination) if destination else root / "dist" / f"KindleAutoPrepare-{version}.zip"
    if destination.suffix.lower() != ".zip":
        raise ValueError("The build destination must be a ZIP file.")
    # Read every required input before creating/replacing the output.
    entries = [(name, (root / "plugin" / name).read_bytes()) for name in PLUGIN_FILES]
    entries.append(("README.md", (root / "README.md").read_bytes()))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name, data in entries:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Output ZIP (default: dist/KindleAutoPrepare-VERSION.zip)")
    arguments = parser.parse_args()
    print(build_plugin(destination=arguments.output))
