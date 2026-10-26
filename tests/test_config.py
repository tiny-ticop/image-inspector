from pathlib import Path
from argparse import Namespace
import json
import tempfile
import unittest
from loom_tools.config import resolve
from loom_tools.demo import generate


class ConfigTests(unittest.TestCase):
    def test_relative_paths_overrides_and_no_masks_for_viewer(self):
        with tempfile.TemporaryDirectory(prefix='image tools ') as temp:
            folder=Path(temp)/'日本語 folder';file=generate(folder)
            args=Namespace(config=file,raw_dir=None,mask_dir=None,output_dir=None,port=None)
            runtime=resolve(args,'frame_viewer')
            self.assertEqual(runtime.raw_dir,folder/'data'/'raw')
            self.assertEqual(runtime.output_dir,folder/'outputs'/'frame_viewer')
            args.output_dir=Path(temp)/'別 results';args.port=8788
            self.assertEqual(resolve(args,'frame_viewer').port,8788)
            data=json.loads(file.read_text());data['mask_dir']='absent masks';file.write_text(json.dumps(data))
            self.assertEqual(resolve(args,'frame_viewer').raw_dir,runtime.raw_dir)
            with self.assertRaises(ValueError):resolve(args,'mask_review_tool')
            args.output_dir=runtime.raw_dir/'generated'
            with self.assertRaises(ValueError):resolve(args,'frame_viewer')

    def test_missing_and_unknown_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'config.json';file.write_text('{"wrong":1}')
            args=Namespace(config=file,raw_dir=None,mask_dir=None,output_dir=None,port=None)
            with self.assertRaises(ValueError):resolve(args,'frame_viewer')
            file.write_text('{"raw_dir":"not here"}')
            with self.assertRaises(ValueError):resolve(args,'frame_viewer')


if __name__=='__main__':unittest.main()
