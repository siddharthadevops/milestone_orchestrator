"""The proportional suite used by milestone suite_checkpoint gates."""

from . import suite_manifest


def load_tests(loader, tests, pattern):
    return suite_manifest.checkpoint_suite(loader)
