"""Build index.html from src.html, embedding every {{img/file}} as a data URI
so the page works as a single self-contained file. Also stamps a version
(hash of the page) into the page and into version.json, which open copies
of the site poll so they reload themselves after a new deploy."""
import base64, hashlib, json, pathlib, re

here = pathlib.Path(__file__).parent
mime = {'png': 'image/png', 'webp': 'image/webp', 'jpg': 'image/jpeg'}

def data_uri(m):
    f = here / 'img' / m.group(1)
    return 'data:%s;base64,%s' % (mime[f.suffix[1:]], base64.b64encode(f.read_bytes()).decode())

src = (here / 'src.html').read_text()
out = re.sub(r'\{\{([\w.-]+\.(?:png|webp|jpg))\}\}', data_uri, src)
version = hashlib.sha1(out.encode()).hexdigest()[:10]
out = out.replace('{{VERSION}}', version)
(here / 'index.html').write_text(out)
(here / 'version.json').write_text(json.dumps({'v': version}) + '\n')
print('index.html', len(out) // 1024, 'KB, version', version)
