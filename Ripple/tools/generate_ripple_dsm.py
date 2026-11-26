"""Generate the Ripple server package DSM from explicit internal Java imports."""
from pathlib import Path
from collections import Counter
from functools import lru_cache
import re
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'Ripple/ripple-server/src/main/java'
OUT = ROOT / 'docs/figures/ripple-package-dsm-mirrored.png'


def read_edges():
    packages = set()
    refs = Counter()
    for path in sorted(SRC.rglob('*.java')):
        text = path.read_text(encoding='utf-8')
        text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
        source = re.search(r'^\s*package\s+([\w.]+);', text, re.M)[1]
        packages.add(source)
        for target_type in set(re.findall(r'^\s*import\s+(ripple\.server\.[\w.]+);', text, re.M)):
            target = target_type.rsplit('.', 1)[0]
            if target != source:
                refs[source, target] += 1
    return sorted(packages), refs


@lru_cache(None)
def font(size):
    return ImageFont.truetype('msyh.ttc', size)


def render(packages, edges):
    size, left, top = 48, 464, 148
    right = left + size * len(packages)
    bottom = top + size * len(packages)
    image = Image.new('RGB', (right + 34, bottom + 145), 'white')
    draw = ImageDraw.Draw(image)

    def label(x, y, text, pts=19, color='#21231f', anchor='lm'):
        draw.text((x, y), str(text), font=font(pts), fill=color, anchor=anchor)

    label(32, 44, 'Ripple 服务端包依赖矩阵', 37)
    label(32, 93, '以行包为视角   /   绿色表示导入列包，蓝色表示被列包导入', 20)
    for i, source in enumerate(packages):
        y = top + i * size
        xhead = left + i * size
        shade = ['#faf4be', '#f1e8a0'][i % 2]
        draw.rectangle((32, y, left-1, y+size-1), fill=shade)
        draw.rectangle((xhead, top-32, xhead+size-1, top-1), fill=shade)
        label(xhead+size/2, top-17, i, anchor='mm')
        label(43, y+size/2, source, 18)
        label(left-20, y+size/2, i, anchor='mm')
        for j, target in enumerate(packages):
            x = left+j*size
            outgoing = edges[source, target]
            incoming = edges[target, source]
            color = ['#fffce0', '#f6f1c5'][(i+j)%2]
            value = ''
            if outgoing and incoming:
                color = '#a32c28'
                value = f'{outgoing}/{incoming}'
            elif outgoing:
                color = '#14743c'
                value = str(outgoing)
            elif incoming:
                color = '#353889'
                value = str(incoming)
            draw.rectangle((x,y,x+size-1,y+size-1), fill=color)
            if i == j:
                draw.line((x,y,x+size-1,y+size-1), fill='#444638', width=2)
            elif value:
                label(x+size/2,y+size/2,value,16 if '/' in value else 22,'white','mm')
    draw.rectangle((left-1,top-1,right,bottom),outline='#484937',width=2)
    label(32,bottom+36,'数字按显式 import 统计，每个源文件对同一类型计一次。红格中两个数依次为行包的导入数和被导入数。',19)
    x = 32
    for color, text in [('#a32c28','两包互相导入'),('#14743c','行包导入列包'),('#353889','列包导入行包')]:
        draw.rectangle((x,bottom+76,x+21,bottom+97),fill=color)
        label(x+32,bottom+87,text,19)
        x += 275
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, dpi=(180,180))


if __name__ == '__main__':
    packages, edges = read_edges()
    render(packages, edges)
    print(OUT, len(packages), 'packages')
    for direction in [('core','ui'), ('ui','core')]:
        print(direction, edges[tuple('ripple.server.' + p for p in direction)])

