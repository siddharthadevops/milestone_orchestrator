"""The manual complement containing exhaustive and slow verification."""

from . import suite_manifest


def load_tests(loader, tests, pattern):
    return suite_manifest.extended_suite(loader)
