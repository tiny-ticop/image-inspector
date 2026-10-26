"""Small synthetic images only; no production data or dependencies beyond Pillow."""
from pathlib import Path
import argparse
import json
import math
import random
from PIL import Image,ImageDraw


def generate(destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    rng=random.Random(42)
    for machine in ['demo_A','demo_B']:
        for angle in [95,96,100]:
            for i in range(4):
                image=Image.new('RGB',(256,192),(45+i*3,55+i*3,60+i*3));draw=ImageDraw.Draw(image)
                mask=Image.new('L',image.size);md=ImageDraw.Draw(mask)
                draw.rectangle((185,55,240,175),fill=(100,110,115));draw.rectangle((15,20,25,170),fill=(150,155,160))
                for offset in range(0,35,5):
                    y=65+offset+(angle-95)*2
                    draw.line((30,y,230,y+30),fill=(215,220,225),width=2);md.line((30,y,230,y+30),fill=1,width=2)
                y=132+int(math.sin(i+angle)*6);x=80+(10 if machine=='demo_B' else 0)
                points=[(x,y),(x+12,y-4),(x+25,y+2),(x+35,y-2)]
                draw.line(points,fill=(240,235,200),width=2);md.line(points,fill=1,width=2)
                # Deterministic gentle appearance changes and a phase-varying structure.
                for _ in range(30):
                    px,py=rng.randrange(30,180),rng.randrange(70,180);draw.point((px,py),fill=(65,75,80))
                draw.text((8,5),f'SYNTHETIC {machine} {angle} {i}',fill=(120,230,130))
                relative=Path(machine)/'delay'/str(angle)/f'frame_{i:03}'
                raw=destination/'data'/'raw'/relative.with_suffix('.jpg');mp=destination/'data'/'masks'/relative.with_suffix('.png')
                raw.parent.mkdir(parents=True,exist_ok=True);mp.parent.mkdir(parents=True,exist_ok=True)
                image.save(raw,quality=93);mask.save(mp)
    config=dict(raw_dir='./data/raw',mask_dir='./data/masks',frame_viewer=dict(output_dir='./outputs/frame_viewer',port=8769),mask_review_tool=dict(output_dir='./outputs/mask_review_tool',port=8765))
    (destination/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    return destination/'config.json'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'examples'/'demo');args=parser.parse_args()
    print(generate(args.output))


if __name__=='__main__':main()
