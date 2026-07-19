"""
Application version metadata.

__version__ is real, hand-maintained software versioning - bump it when
you cut a release. BUILD_TIME is intentionally NOT hardcoded here: a
literal timestamp in source would be wrong the moment it's not
regenerated at build time. Real build tooling (Docker build arg, CI
pipeline) should set the APP_BUILD_TIME env var at deploy time; if it's
unset, the Settings page says exactly that instead of showing a
fabricated time.
"""

__version__ = "1.0.0"