# Changelog

## v1.0.7 — 2026-03-04

### Bug Fix
- **Fixed non-ImportError crash on plugin load (line 26 of main.py)** in AstrBot v4.18.1.

### Root Cause
`main.py` was inserting the plugin directory into `sys.path` **before** importing
`astrbot.api.event.filter`. On first load, Python has not yet cached
`astrbot.api.event.filter` in `sys.modules`, so it triggers a full import of
`astrbot.core.star.register.star_handler` (which has heavy transitive imports).
If any of those transitive imports raises a non-`ImportError` exception (e.g.
`RuntimeError` from a partially-initialised module, or `AttributeError` from
a circular-import edge case) the inner recovery handler at
`star_manager._import_plugin_with_dependency_recovery` only catches
`(ModuleNotFoundError, ImportError)`, so the exception propagates uncaught to
the outer `except Exception` at star_manager:532.

### Fix
1. **Moved `sys.path.insert` to after the AstrBot API imports** so the
   plugin directory is only added to `sys.path` after all of AstrBot's own
   modules have already been loaded/cached, eliminating any risk of our plugin
   dir interfering with their loading.
2. **Removed unused `MessageEventResult` import** from `astrbot.api.event`.
3. **Widened `except ImportError` → `except Exception`** in the optional
   `numpy` / `aiohttp` guards in `speedbot_core/semantic_cache.py` and
   `speedbot_core/connection_pool.py` so a broken optional dependency
   installation (e.g. numpy raises `RuntimeError` instead of `ImportError`)
   is caught and the graceful "unavailable" fallback is used.

### Release tag note
As documented previously, release tags must use underscores instead of dots
(e.g. `v1_0_7`).

---

### Bug Fix
- **Fixed `KeyError: 'items'` on plugin load** when installing via zip upload
  in AstrBot v4.18.1+.

### Root Cause
AstrBot's config schema parser (`astrbot_config.py`, `_parse_schema`) expects
nested object schemas to use the key `"items"` for sub-fields. The plugin's
`_conf_schema.json` was incorrectly using the JSON Schema keyword `"properties"`
instead, causing:

```
KeyError: 'items'
  File "astrbot_config.py", line 82, in _parse_schema
      _parse_schema(v["items"], conf[k])
```

Every object-type config section (`semantic_cache`, `intent_router`,
`connection_pool`, `priority_queue`, `monitor`, `deepseek_reasoner`) triggered
this error on plugin initialisation.

### Fix
Renamed `"properties"` → `"items"` in every object entry of
`_conf_schema.json` to match the key AstrBot's parser expects.

### Release tag note
As documented in v1.0.5, release tags must use underscores instead of dots
(e.g. `v1_0_6`). The version in `metadata.yaml` remains standard PEP 440
(`1.0.6`).

---

## v1.0.5 — 2026-03-04

### Bug Fix
- **Fixed `ModuleNotFoundError` on plugin load** caused by dots in the installed
  folder name when the plugin is installed via manual zip upload.

### Root Cause
AstrBot constructs the Python import path as `data.plugins.<dir_name>.main`,
where `<dir_name>` comes from the uploaded zip filename.  Release tag `v1.04`
produced a zip called `astrbot_plugin_speedbot-1.04.zip`; after AstrBot adds
the `plugin_upload_` prefix the folder became
`plugin_upload_astrbot_plugin_speedbot-1.04`.  Python's `__import__` splits on
**all** dots, so it tried to import the non-existent sub-package
`plugin_upload_astrbot_plugin_speedbot-1` and failed with:

```
ModuleNotFoundError: No module named 'data.plugins.plugin_upload_astrbot_plugin_speedbot_1'
```

### Fix
Future release tags **must use underscores instead of dots** in the version
component (e.g. `v1_0_5`, not `v1.0.5`).  GitHub turns `v1_0_5` into the zip
name `astrbot_plugin_speedbot-1_0_5.zip`; no extra dots appear in the folder
name, so the import path is always valid.

The version in `metadata.yaml` remains standard PEP 440 (`1.0.5`) for
AstrBot's version-comparison / update-checker logic.

### Migration for users with a broken v1.04 installation
1. In the AstrBot dashboard, uninstall the plugin (this removes the broken
   `plugin_upload_astrbot_plugin_speedbot_1.04` directory).
2. Reinstall via the **marketplace repo URL** (preferred) or by uploading the
   new zip downloaded from the `v1_0_5` release.

---

## v1.0.4 — 2026-02-XX

### Bug Fix
- Renamed internal sub-packages `core/` → `speedbot_core/` and
  `utils/` → `speedbot_utils/` to fix a namespace conflict with AstrBot's own
  `core` module that caused `ModuleNotFoundError: No module named 'core.async_executor'`.
