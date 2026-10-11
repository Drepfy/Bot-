#!/usr/bin/env python3
"""Static check for WPF XAML resource references.

A missing StaticResource key only fails at runtime (XamlParseException when the view loads), so the
build cannot catch it. This script verifies that every StaticResource/DynamicResource key used in the
application's XAML is defined in one of its resource dictionaries (or set at runtime by ThemeManager),
and that all theme dictionaries define the same brush keys.

Usage: python3 scripts/check-xaml-resources.py [path/to/src/CleanerPro.App]
Exit code 0 = OK, 1 = problems found.
"""
import pathlib
import re
import sys

app = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent / "src" / "CleanerPro.App")
xaml_files = sorted(app.rglob("*.xaml"))
xaml_files = [f for f in xaml_files if "obj" not in f.parts and "bin" not in f.parts]

key_pattern = re.compile(r'x:Key="([^"]+)"')
ref_pattern = re.compile(r'\{(StaticResource|DynamicResource)\s+([^}\s]+)\s*\}')

# Keys defined in any dictionary (themes, styles, local resources).
defined = set()
for file in xaml_files:
    defined.update(key_pattern.findall(file.read_text(encoding="utf-8")))

# Keys assigned at runtime by ThemeManager (Application.Resources[...] = ...).
theme_manager = (app / "Services" / "ThemeManager.cs").read_text(encoding="utf-8")
defined.update(re.findall(r'app\.Resources\["([^"]+)"\]', theme_manager))

problems = []
for file in xaml_files:
    text = file.read_text(encoding="utf-8")
    for kind, key in ref_pattern.findall(text):
        if key.startswith("{x:Type") or key.startswith("{x:Static"):
            continue
        if key not in defined:
            problems.append(f"{file.relative_to(app)}: {kind} '{key}' is not defined")

# Every theme must define the same brushes so switching themes never leaves a key unresolved.
themes = {f.stem: set(key_pattern.findall(f.read_text(encoding="utf-8"))) for f in (app / "Themes").glob("*.xaml") if f.stem != "Styles"}
all_keys = set().union(*themes.values()) if themes else set()
for name, keys in themes.items():
    for missing in sorted(all_keys - keys):
        problems.append(f"Themes/{name}.xaml: missing brush '{missing}' defined by other themes")

# Code-behind lookups (FindResource / TryFindResource) must also resolve.
for cs in app.rglob("*.cs"):
    if "obj" in cs.parts or "bin" in cs.parts:
        continue
    for key in re.findall(r'(?:Try)?FindResource\("([^"]+)"\)', cs.read_text(encoding="utf-8")):
        if key not in defined:
            problems.append(f"{cs.relative_to(app)}: resource '{key}' is not defined")
    for key in re.findall(r'"(Brush\.[A-Za-z.]+)"', cs.read_text(encoding="utf-8")):
        if key not in defined:
            problems.append(f"{cs.relative_to(app)}: brush '{key}' is not defined")

if problems:
    print("XAML resource check FAILED:")
    for problem in problems:
        print("  - " + problem)
    sys.exit(1)

print(f"XAML resource check passed: {len(xaml_files)} XAML files, {len(defined)} keys, {len(themes)} themes consistent.")
