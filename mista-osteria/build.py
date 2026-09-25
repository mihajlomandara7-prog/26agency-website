"""Build index.html from src.html, embedding every {{img/file}} as a data URI
so the page works as a single self-contained file."""
import base64, pathlib, re

here = pathlib.Path(__file__).parent
mime = {'png': 'image/png', 'webp': 'image/webp', 'jpg': 'image/jpeg'}

def data_uri(m):
    f = here / 'img' / m.group(1)
    return 'data:%s;base64,%s' % (mime[f.suffix[1:]], base64.b64encode(f.read_bytes()).decode())

src = (here / 'src.html').read_text()
out = re.sub(r'\{\{([\w.-]+)\}\}', data_uri, src)
(here / 'index.html').write_text(out)
print('index.html', len(out) // 1024, 'KB')
