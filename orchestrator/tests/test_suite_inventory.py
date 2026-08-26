"""Mechanical proof that the explicit suites retain the full catalogue."""

from collections import Counter
import unittest

from . import suite_manifest


class SuiteInventoryTest(unittest.TestCase):
    def test_checkpoint_and_extended_partition_every_retained_test(self):
        loader = unittest.TestLoader()
        retained = list(suite_manifest.iter_tests(
            suite_manifest.retained_suite(loader)
        ))
        checkpoint = list(suite_manifest.iter_tests(
            suite_manifest.checkpoint_suite(loader)
        ))
        extended = list(suite_manifest.iter_tests(
            suite_manifest.extended_suite(loader)
        ))

        retained_ids = [test.id() for test in retained]
        checkpoint_ids = [test.id() for test in checkpoint]
        extended_ids = [test.id() for test in extended]
        inherited_origins = [
            (
                test.__class__.__module__,
                getattr(
                    getattr(test.__class__, test._testMethodName, None),
                    "__qualname__",
                    None,
                ),
            )
            for test in retained
        ]
        self.assertEqual(
            [test_id for test_id, count in Counter(retained_ids).items()
             if count != 1],
            [],
        )
        self.assertEqual(
            [origin for origin, count in Counter(inherited_origins).items()
             if count != 1],
            [],
        )
        self.assertEqual(set(checkpoint_ids) & set(extended_ids), set())
        self.assertEqual(
            set(checkpoint_ids) | set(extended_ids), set(retained_ids)
        )
        self.assertEqual(len(checkpoint_ids) + len(extended_ids), len(retained_ids))


if __name__ == "__main__":
    unittest.main()
