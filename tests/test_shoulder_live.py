# SPDX-License-Identifier: GPL-2.0-or-later
"""Check native live shoulder pixels against original main-dial state changes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://127.0.0.1:8787')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    def get(path):
        with urllib.request.urlopen(a.url+path, timeout=5) as response:
            return response.read()
    token = re.search(r"const token='([^']+)'", get('/').decode())[1]
    def state():
        return json.loads(get('/api/status'))
    def action(name, key=None):
        request = urllib.request.Request(a.url+'/api/action',
            data=json.dumps(dict(action=name, key=key)).encode(),
            headers={'Content-Type':'application/json','X-Z6-Token':token})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)
    def wait(predicate):
        deadline = time.monotonic()+45
        while time.monotonic() < deadline:
            value = state()
            if value.get('error'):
                raise RuntimeError(value['error'])
            if predicate(value):
                return value
            time.sleep(.2)
        raise TimeoutError('Shoulder state did not reach expected condition')
    def save(name, value):
        png = get('/api/shoulder')
        (a.out/(name+'.png')).write_bytes(png)
        value['shoulder_png_sha256'] = hashlib.sha256(png).hexdigest()
        (a.out/(name+'.json')).write_text(json.dumps(value, indent=2))
        return value
    before = save('before', wait(lambda s:s['phase']=='running' and not s['busy'] and s.get('shoulder',{}).get('lit_pixels',0)>0))
    request = action('key','main_ccw')
    after = save('dial', wait(lambda s:not s['busy'] and s.get('completed_action',0)>=request['id'] and s['shoulder']['framebuffer_sha256']!=before['shoulder']['framebuffer_sha256']))
    assert after['exposure']['tv'] != before['exposure']['tv']
    request = action('key','main_cw')
    restored = save('restored', wait(lambda s:not s['busy'] and s.get('completed_action',0)>=request['id'] and s['exposure']['tv']==before['exposure']['tv'] and s['shoulder']['framebuffer_sha256']==before['shoulder']['framebuffer_sha256']))
    action('pause')
    paused = save('paused', wait(lambda s:s['phase']=='paused' and not s['busy']))
    time.sleep(1)
    stable = state()
    assert stable['shoulder']['framebuffer_sha256']==paused['shoulder']['framebuffer_sha256']
    assert stable['shoulder']['packets']==paused['shoulder']['packets']
    action('resume')
    resumed = wait(lambda s:s['phase']=='running' and not s['busy'])
    report = dict(passed=True, cases=['native-dial-changes-Tv-and-shoulder-pixels',
        'reverse-dial-restores-Tv-and-pixels','paused-shoulder-stable','resume'],
        session=before['session'], before_tv=before['exposure']['tv'], after_tv=after['exposure']['tv'],
        before_hash=before['shoulder']['framebuffer_sha256'], after_hash=after['shoulder']['framebuffer_sha256'],
        renderer=resumed['shoulder'], camera_tested=False)
    (a.out/'validation.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
