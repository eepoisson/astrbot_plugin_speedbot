# Changelog

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
