"""Optional browser edge-case checks with in-memory test fixtures only.
Requires Playwright and Chromium; see browser_smoke.py for setup.
No author records or photographs are changed by this test.
"""
import asyncio,copy,json,sys,mimetypes,os,shutil
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'tools'))
from birding_common import load_places,build_index
original=load_places(ROOT)
examples=[place for place in original if place['demo']]
real=copy.deepcopy(examples[0]); real.update(id='test-real',name='Real Test Location',demo=False)
real['visits']=real['visits'][:1]
real['visits'][0]['observations']=real['visits'][0]['observations'][:1]
real['visits'][0].update(id='test-2026',date='2026-08-02',notes='Newer visit')
obs=real['visits'][0]['observations'][0]
obs.update(speciesId='mallard',nameEn='Mallard',identified=True,scientificName='Anas platyrhynchos')
obs['photos']=obs['photos'][:1]
p2=copy.deepcopy(obs['photos'][0]);p2['src']='photos/testing/second.webp';obs['photos'].append(p2)
past=copy.deepcopy(real['visits'][0]);past.update(id='test-2025',date='2025-05-01',notes='Earlier visit');past['observations'][0]['photos']=[];real['visits'].append(past)
hidden=copy.deepcopy(real); hidden.update(id='test-hidden',name='Hidden Test Location',locationPrecision='hidden',coordinates=None)
nearby=copy.deepcopy(real);nearby.update(id='test-nearby',name='Nearby Test Location',visits=[])
nearby['coordinates']['lng']+=.07
records=examples+[real,nearby,hidden]
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(executable_path=os.environ.get('BIRDING_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome'),args=['--no-sandbox'])
  ctx=await b.new_context(viewport={'width':1280,'height':1000})
  async def route(r):
   u=urlsplit(r.request.url)
   if u.hostname!='localhost': return await r.abort()
   d={'/birding/data/locations.geojson':build_index(records),'/birding/data/places/test-real.json':real,'/birding/data/places/test-hidden.json':hidden}
   if u.path=='/birding/data/birding-data.js':
    payload={'index':build_index(records),'places':{x['id']:x for x in records}}
    return await r.fulfill(body='window.BIRDING_DATA = '+json.dumps(payload)+';',content_type='application/javascript',headers={'Access-Control-Allow-Origin':'*'})
   if u.path in d: return await r.fulfill(json=d[u.path],headers={'Access-Control-Allow-Origin':'*'})
   path=ROOT/u.path.lstrip('/')
   if u.path=='/birding/photos/testing/second.webp':path=ROOT/'birding/photos/demo/homepage-birds.webp'
   if path.is_file(): return await r.fulfill(body=path.read_bytes(),content_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream',headers={'Access-Control-Allow-Origin':'*'})
   return await r.fulfill(status=404,body='No file')
  await ctx.route('**/*',route)
  pg=await ctx.new_page();pg.set_default_timeout(7000); errors=[];pg.on('pageerror',lambda e:errors.append(str(e)))
  html=(ROOT/'birding/index.html').read_text().replace('<head>','''<head><base href="http://localhost/birding/"><script>for(const n of ['pushState','replaceState']){const f=history[n].bind(history);history[n]=(s,t,u)=>f(s,t,new URL(u,location.href).href);}</script>''')
  await pg.set_content(html,wait_until='networkidle')
  await expect(pg.locator('#map-status')).to_contain_text('unavailable')
  await expect(pg.locator('#outline-map')).to_be_visible()
  await expect(pg.locator('#stats strong').first).to_have_text('03')
  assert not await pg.locator('#demo-notice').is_visible()
  assert await pg.locator('.map-point').count()==1
  # Two nearby public locations initially share a cluster; expand it to choose one.
  for _ in range(12):
   if await pg.locator('[data-map-id="test-real"]').count():break
   cluster=pg.locator('.map-point[data-map-id^="cluster-"]').filter(has=pg.locator('title',has_text=real['name'])).first
   await expect(cluster).to_be_visible()
   before=await pg.locator('.overview-svg').get_attribute('viewBox')
   await cluster.click()
   assert before!=await pg.locator('.overview-svg').get_attribute('viewBox'), 'Cluster did not expand'
  await pg.locator('[data-map-id="test-real"]').click()
  await expect(pg.locator('#detail-title')).to_have_text('Real Test Location')
  await pg.locator('.photo-open').first.click()
  await pg.locator('#photo-next').click()
  assert await pg.locator('#photo-counter').inner_text()=='2 / 2'
  await pg.keyboard.press('ArrowLeft'); await expect(pg.locator('#photo-counter')).to_have_text('1 / 2')
  await pg.keyboard.press('Escape')
  await pg.locator('#tab-notes').click()
  await expect(pg.locator('#panel-notes')).to_contain_text('Earlier visit')
  await expect(pg.locator('#panel-notes')).to_contain_text('Newer visit')
  await pg.evaluate("location.hash = '#test-hidden'")
  await expect(pg.locator('#detail-title')).to_have_text('Hidden Test Location')
  assert 'Location withheld' in await pg.locator('.location-meta').first.inner_text()
  # Hidden locations remain reachable by deep link, while public pins support keyboard selection.
  await pg.locator('[data-map-id="test-real"]').focus();await pg.keyboard.press('Enter')
  await expect(pg.locator('#detail-title')).to_have_text('Real Test Location')
  for w in [320,375,760,768,1024,1440]:
   await pg.set_viewport_size({'width':w,'height':900});await pg.wait_for_timeout(60)
   assert await pg.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),w
  assert not errors, errors
  print('Extra UI checks passed: automatic tile failure fallback, demo exclusion, real/hidden records, clustered map click/keyboard, hidden deep link, multi-photo navigation, all visit notes, widths 320–1440.')
  await b.close()
asyncio.run(main())
