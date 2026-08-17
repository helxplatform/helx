from __future__ import annotations

import runpy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROMOTION = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "release-promote.py")
)
PromotionError = PROMOTION["ReleaseError"]
materialize = PROMOTION["materialize"]
promote = PROMOTION["promote"]
verify_build_digests = PROMOTION["verify_build_digests"]


class BootstrapMaterializationTests(unittest.TestCase):
    staging_ref = "containers.renci.org/helxplatform/appstore:staging_abc123"
    release_ref = "containers.renci.org/helxplatform/appstore:v1.0.0"

    def plan(self, *, bootstrap: bool) -> dict:
        return {
            "mode": "release",
            "already_released": False,
            "release": {"tag": "v4.5.7", "bootstrap": bootstrap},
            "build_images": [
                {
                    "name": "appstore",
                    "staging_ref": self.staging_ref,
                    "release_ref": self.release_ref,
                    "promote": True,
                }
            ],
            "components": [
                {
                    "name": "appstore",
                    "images": [
                        {
                            "name": "appstore",
                            "release_ref": self.release_ref,
                            "staging_ref": self.staging_ref,
                            "digest": None,
                            "immutable_ref": None,
                        }
                    ],
                }
            ],
        }

    def test_bootstrap_preserves_existing_semantic_digest(self) -> None:
        existing_digest = "sha256:" + "1" * 64
        inspect = Mock(return_value=existing_digest)
        promote_image = Mock()
        with patch.dict(
            materialize.__globals__,
            {"inspect_digest": inspect, "promote": promote_image},
        ):
            manifest = materialize(self.plan(bootstrap=True), "helx-monorepo-release")

        image = manifest["components"][0]["images"][0]
        self.assertEqual(image["digest"], existing_digest)
        self.assertEqual(
            image["immutable_ref"],
            "containers.renci.org/helxplatform/appstore@" + existing_digest,
        )
        inspect.assert_called_once_with(self.release_ref, allow_missing=True)
        promote_image.assert_not_called()

    def test_bootstrap_promotes_staging_when_semantic_ref_is_missing(self) -> None:
        staged_digest = "sha256:" + "2" * 64
        inspect = Mock(return_value=None)
        promote_image = Mock(return_value=staged_digest)
        with patch.dict(
            materialize.__globals__,
            {"inspect_digest": inspect, "promote": promote_image},
        ):
            manifest = materialize(self.plan(bootstrap=True), "helx-monorepo-release")

        image = manifest["components"][0]["images"][0]
        self.assertEqual(image["digest"], staged_digest)
        self.assertEqual(
            image["immutable_ref"],
            "containers.renci.org/helxplatform/appstore@" + staged_digest,
        )
        inspect.assert_called_once_with(self.release_ref, allow_missing=True)
        promote_image.assert_called_once_with(self.staging_ref, self.release_ref, None)

    def test_non_bootstrap_promotion_rejects_different_existing_digest(self) -> None:
        staged_digest = "sha256:" + "3" * 64
        existing_digest = "sha256:" + "4" * 64
        inspect = Mock(side_effect=[staged_digest, existing_digest])
        with patch.dict(
            promote.__globals__, {"inspect_digest": inspect}
        ), self.assertRaisesRegex(PromotionError, "Refusing to overwrite"):
            promote(self.staging_ref, self.release_ref)

    def test_build_digest_handoff_rejects_a_moved_staging_tag(self) -> None:
        expected_digest = "sha256:" + "5" * 64
        moved_digest = "sha256:" + "6" * 64
        plan = self.plan(bootstrap=False)
        expected = {
            "appstore": {
                "staging_ref": self.staging_ref,
                "digest": expected_digest,
            }
        }
        with patch.dict(
            verify_build_digests.__globals__,
            {"inspect_digest": Mock(return_value=moved_digest)},
        ), self.assertRaisesRegex(PromotionError, "moved after its build"):
            verify_build_digests(plan, expected)

    def test_unchanged_image_is_verified_against_registry(self) -> None:
        digest = "sha256:" + "7" * 64
        plan = self.plan(bootstrap=False)
        plan["build_images"] = []
        plan["components"][0]["images"][0]["digest"] = digest
        plan["components"][0]["images"][0]["immutable_ref"] = (
            "containers.renci.org/helxplatform/appstore@" + digest
        )
        with patch.dict(
            materialize.__globals__,
            {"inspect_digest": Mock(return_value="sha256:" + "8" * 64)},
        ), self.assertRaisesRegex(PromotionError, "no longer matches"):
            materialize(plan, "helx-monorepo-release")


if __name__ == "__main__":
    unittest.main()
