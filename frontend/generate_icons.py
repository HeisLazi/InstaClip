from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
icons_dir = Path('icons')
icons_dir.mkdir(exist_ok=True)
for size in [32, 128]:
    img = Image.new('RGBA', (size, size), (0, 122, 204, 255))
    d = ImageDraw.Draw(img)
    text = 'I'
    try:
        font = ImageFont.truetype('arial.ttf', size - 8)
    except Exception:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - w) / 2, (size - h) / 2), text, fill='white', font=font)
    img.save(icons_dir / f'{size}x{size}.png')
imgs = [Image.open(icons_dir / '32x32.png'), Image.open(icons_dir / '128x128.png')]
imgs[0].save(icons_dir / 'icon.ico', format='ICO', sizes=[(32, 32), (128, 128)])
print('created icons')
