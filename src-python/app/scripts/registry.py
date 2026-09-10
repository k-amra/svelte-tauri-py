"""Auto-discovers scripts in app/scripts/.

Adding a new capability = drop a file in scripts/ with
Params / Result / NAME / DESCRIPTION / run(). No router changes needed.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from types import ModuleType

import app.scripts as scripts_pkg
from frozen_scripts import FROZEN_SCRIPTS  # top-level module, next to app/

log = logging.getLogger(__name__)

# PyInstaller puts imported modules in its PYZ archive, where filesystem
# discovery is not reliable. Keep this list in sync with api_server.spec.
FROZEN_MODULES = FROZEN_SCRIPTS


def discover() -> dict[str, ModuleType]:
    registry: dict[str, ModuleType] = {}
    names = set(FROZEN_MODULES)
    if not getattr(sys, "frozen", False):
        names.update(
            mod_info.name
            for mod_info in pkgutil.iter_modules(scripts_pkg.__path__)
            if not mod_info.name.startswith("_") and mod_info.name != "registry"
        )
    for name in sorted(names):
        if name.startswith("_") or name == "registry":
            continue
        try:
            module = importlib.import_module(f"app.scripts.{name}")
        except Exception as e:
            log.error("Failed to import script '%s': %s — skipping", name, e)
            continue
        name = getattr(module, "NAME", name)
        if not hasattr(module, "run"):
            continue
        registry[name] = module
    return registry


REGISTRY: dict[str, ModuleType] = discover()


def metadata() -> list[dict]:
    items = []
    for name, mod in sorted(REGISTRY.items()):
        params_schema: dict = {}
        result_schema: dict = {}
        if hasattr(mod, "Params") and hasattr(mod.Params, "model_json_schema"):
            params_schema = mod.Params.model_json_schema()
        if hasattr(mod, "Result") and hasattr(mod.Result, "model_json_schema"):
            result_schema = mod.Result.model_json_schema()
        items.append(
            {
                "name": name,
                "description": getattr(mod, "DESCRIPTION", ""),
                "params_schema": params_schema,
                "result_schema": result_schema,
            }
        )
    return items
