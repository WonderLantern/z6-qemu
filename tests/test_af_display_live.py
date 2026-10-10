# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify the invalid AF corner is absent while diagnostic AF remains usable."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import time
import urllib.request
import numpy as np
from PIL import Image


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--url', default='http://127.0.0.1:8787')
    p.add_argument('--out', type=Path, required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    def get(path):
        with urllib.request.urlopen(a.url+path,timeout=5) as response:return response.read()
    token=re.search(r"const token='([^']+)'",get('/').decode())[1]
    def wait(predicate):
        end=time.monotonic()+60
        while time.monotonic()<end:
            s=json.loads(get('/api/status'))
            if s.get('error'):raise RuntimeError(s['error'])
            if predicate(s):return s
            time.sleep(.2)
        raise TimeoutError('Expected UI state not reached')
    def key(name):
        request=urllib.request.Request(a.url+'/api/action',
            data=json.dumps(dict(action='key',key=name)).encode(),
            headers={'Content-Type':'application/json','X-Z6-Token':token})
        with urllib.request.urlopen(request,timeout=5) as response:item=json.load(response)
        return wait(lambda s:not s['busy'] and s.get('completed_action',0)>=item['id'])
    cases=[]
    def capture(name,s,changed_from=None,expect_red=None):
        end=time.monotonic()+5
        while True:
            png=get('/api/frame')
            image=np.asarray(Image.open(BytesIO(png)).convert('RGB'))
            red=(image[:,:,0]>=240)&(image[:,:,1]<=8)&(image[:,:,2]<=8)
            diagnostic_red=int(red[100:500,200:600].sum())
            changed=changed_from is None or np.count_nonzero(np.any(image!=changed_from,axis=2))>100
            color_ready=expect_red is None or ((diagnostic_red>100) if expect_red else diagnostic_red==0)
            if changed and color_ready:break
            if time.monotonic()>end:raise AssertionError((name,'native LCD pixels did not change'))
            time.sleep(.2)
        (a.out/(name+'.png')).write_bytes(png)
        red=(image[:,:,0]>=240)&(image[:,:,1]<=8)&(image[:,:,2]<=8)
        corner=int(red[:52,:48].sum())
        assert corner==0,(name,corner)
        cases.append(dict(name=name,corner_red_pixels=corner,diagnostic_red_pixels=diagnostic_red,
                          focus=s.get('focus'),shoulder=s.get('shoulder')))
        return image,diagnostic_red
    s=wait(lambda s:s['phase']=='running' and not s['busy'] and s.get('shoulder',{}).get('lit_pixels',0)>0)
    if not s.get('focus',{}).get('enabled'):key('af_s')
    key('af_idle')
    s=key('af_toggle');time.sleep(.4)
    baseline,_=capture('default',s)
    small,_=capture('s',key('af_s'),baseline)
    large,_=capture('l',key('af_l'),small)
    assert np.count_nonzero(np.any(small!=baseline,axis=2))>100
    assert np.count_nonzero(np.any(large!=small,axis=2))>100
    failed,red=capture('failed',key('af_failed'),large,True);assert red>100
    off,red=capture('off',key('af_toggle'),failed,False);assert red==0
    key('af_l')
    capture('final_l',key('af_idle'),off,False)
    result=dict(passed=True,cases=cases,test_modifies_firmware=False,
                scope='no-lens invalid-input display guard and independent GPU AF diagnostic',
                optical_af_verified=False)
    (a.out/'validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(passed=True,cases=[v['name'] for v in cases])))


if __name__=='__main__':main()
