from pathlib import Path
import importlib.util
import unittest

spec=importlib.util.spec_from_file_location('export_source',Path(__file__).resolve().parents[1]/'scripts/export_source.py')
export=importlib.util.module_from_spec(spec);spec.loader.exec_module(export)


class ReleaseTests(unittest.TestCase):
    def test_only_code_and_synthetic_images(self):
        for name in ['frame_viewer/server.py','mask_review_tool/viewer/app.js','examples/demo/data/raw/demo_A/delay/95/frame_000.jpg','README.md']:
            self.assertTrue(export.allowed(name),name)
        for name in ['data/raw/image.jpg','frame_viewer/outputs/features.npz','mask_review_tool/reviews.json','frame_viewer/model.joblib','thread_classification/model.py','config.local.json','.venv/python.exe','../outside','frame_viewer/photo.jpg']:
            self.assertFalse(export.allowed(name),name)


if __name__=='__main__':unittest.main()
