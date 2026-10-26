from dataclasses import dataclass
from pathlib import Path
import argparse
import json

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ToolConfig:
    raw_dir: Path
    mask_dir: Path
    output_dir: Path
    port: int


def add_arguments(parser):
    parser.add_argument('--config', type=Path, help='JSON configuration file')
    parser.add_argument('--raw-dir', type=Path, help='Root containing machine/delay/angle/*.jpg')
    parser.add_argument('--mask-dir', type=Path, help='Root containing corresponding PNG masks')
    parser.add_argument('--output-dir', type=Path, help='Result directory (not inside input directories)')
    parser.add_argument('--port', type=int, help='Local TCP port')


def resolve(args, tool):
    document={};base=REPO
    if getattr(args,'config',None) is not None:
        path=args.config.expanduser().resolve();base=path.parent
        try:document=json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError) as error:raise ValueError(f'Cannot read config {path}: {error}') from error
        if not isinstance(document,dict) or set(document)-{'raw_dir','mask_dir','frame_viewer','mask_review_tool'}:raise ValueError('Unknown configuration field')
    section=document.get(tool,{})
    if not isinstance(section,dict) or set(section)-{'output_dir','port'}:raise ValueError('Unknown tool configuration field')
    def path_for(flag,value,default):
        cli=getattr(args,flag,None)
        if cli is not None:return cli.expanduser().resolve()
        if value is None:return default.resolve()
        if not isinstance(value,str) or not value.strip():raise ValueError(f'Invalid {flag}')
        path=Path(value).expanduser()
        return (path if path.is_absolute() else base/path).resolve()
    raw=path_for('raw_dir',document.get('raw_dir'),REPO/'data'/'raw')
    mask=path_for('mask_dir',document.get('mask_dir'),REPO/'data'/'masks')
    output=path_for('output_dir',section.get('output_dir'),REPO/tool/'outputs')
    port=getattr(args,'port',None)
    if port is None:port=section.get('port',8769 if tool=='frame_viewer' else 8765)
    if type(port) is not int or not 1<=port<=65535:raise ValueError('Port must be between 1 and 65535')
    if not raw.is_dir():raise ValueError(f'Image directory not found: {raw}. Use --raw-dir or --config.')
    if tool=='mask_review_tool' and not mask.is_dir():raise ValueError(f'Mask directory not found: {mask}. Use --mask-dir.')
    if output.is_relative_to(raw) or output.is_relative_to(mask):raise ValueError('Output directory must not be inside an input directory')
    output.mkdir(parents=True,exist_ok=True)
    import tempfile
    try:
        with tempfile.TemporaryFile(dir=output):pass
    except OSError as error:raise ValueError(f'Output directory is not writable: {output}') from error
    return ToolConfig(raw,mask,output,port)


def print_config(config):
    print('Raw: '+str(config.raw_dir),flush=True)
    print('Masks: '+str(config.mask_dir),flush=True)
    print('Output: '+str(config.output_dir),flush=True)
