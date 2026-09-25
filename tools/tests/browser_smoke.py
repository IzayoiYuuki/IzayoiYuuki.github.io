"""Optional developer browser check. Requires Playwright and Chromium.

python3 -m pip install playwright
python3 tools/tests/browser_smoke.py
Set BIRDING_CHROMIUM to a browser executable if it is not on PATH.
No external requests are needed; the test fulfils local resources directly.
Screenshots and results go to the system temporary directory, not the website.
"""
import asyncio, base64, json, math, mimetypes, os, shutil, sys, tempfile
from urllib.parse import urlsplit
from pathlib import Path
from playwright.async_api import async_playwright, expect

BASE='http://127.0.0.1:8000'
OUT=Path(tempfile.gettempdir()) / 'birding-browser-test-output'
OUT.mkdir(exist_ok=True)
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from birding_common import all_photos, load_places, visible_places
places=visible_places(load_places(ROOT))
photo_place=next(place for place in places if place['coordinates'] and all_photos(place))
photo_count=len(all_photos(photo_place))
async def handler(route):
    url=urlsplit(route.request.url)
    if url.hostname not in ['localhost','127.0.0.1']: return await route.abort()
    path=ROOT/url.path.lstrip('/')
    if path.is_dir(): path=path/'index.html'
    if path.is_file():
        await route.fulfill(body=path.read_bytes(),content_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream',headers={'Access-Control-Allow-Origin':'*'})
    else: await route.fulfill(status=404,body='Missing')
async def show(page, relative, fragment=''):
    await page.goto('about:blank'+fragment)
    path=ROOT/relative
    if path.is_dir(): path=path/'index.html'
    base=BASE+'/' + str(path.parent.relative_to(ROOT)).replace('\\','/')+'/'
    if path.parent==ROOT: base=BASE+'/'
    shim="<script>for(const name of ['pushState','replaceState']){const original=history[name].bind(history);history[name]=(state,title,url)=>original(state,title,new URL(url,location.href).href);}</script>"
    text=path.read_text().replace('<head>', '<head><base href="'+base+'">'+shim,1)
    await page.set_content(text,wait_until='networkidle')


async def select_overview_place(page, place):
    """Nearby authored locations share a marker until its cluster is expanded."""
    for _ in range(12):
        marker=page.locator('.map-point[data-map-id="'+place['id']+'"]')
        if await marker.count():
            await marker.click()
            return
        cluster=page.locator('.map-point[data-map-id^="cluster-"]').filter(
            has=page.locator('title',has_text=place['name'])).first
        await expect(cluster).to_be_visible()
        before=await page.locator('.overview-svg').get_attribute('viewBox')
        await cluster.click()
        assert before!=await page.locator('.overview-svg').get_attribute('viewBox'), 'Cluster did not expand'
    raise AssertionError('Location remained clustered: '+place['name'])


async def check_overview_wheel(page):
    svg=page.locator('.overview-svg')
    await svg.scroll_into_view_if_needed()
    box=await svg.bounding_box()
    # WheelEvent client coordinates use CSS pixels; match the dispatched integer position.
    cursor={'x':round(box['x']+box['width']*.31),'y':round(box['y']+box['height']*.43)}
    coordinate="""(svg, cursor) => {
        const point = svg.createSVGPoint(); point.x = cursor.x; point.y = cursor.y;
        const local = point.matrixTransform(svg.getScreenCTM().inverse());
        return [local.x, local.y];
    }"""
    before=await svg.evaluate(coordinate,cursor)
    height=float((await svg.get_attribute('viewBox')).split()[3])
    scroll=await page.evaluate('scrollY')
    await page.mouse.move(cursor['x'],cursor['y'])
    await page.mouse.wheel(0,-240)
    await page.wait_for_function('(height) => document.querySelector(".overview-svg").viewBox.baseVal.height < height',arg=height)
    after=await svg.evaluate(coordinate,cursor)
    assert all(abs(a-b)<1e-5 for a,b in zip(before,after)), (before,after)
    assert abs(await page.evaluate('scrollY')-scroll)<1, 'Map wheel scrolled the page'
    zoomed_height=float((await svg.get_attribute('viewBox')).split()[3])
    await page.mouse.wheel(0,240)
    await page.wait_for_function('(height) => document.querySelector(".overview-svg").viewBox.baseVal.height > height',arg=zoomed_height)
    after_out=await svg.evaluate(coordinate,cursor)
    assert all(abs(a-b)<1e-5 for a,b in zip(before,after_out)), (before,after_out)


async def check_city_labels(page):
    # Zoom towards northern England; both cities should be legible in one regional view.
    await page.locator('#reset-view').click()
    svg=page.locator('.overview-svg')
    await svg.scroll_into_view_if_needed()
    projected_y=-math.log(math.tan(math.pi/4+53.6*math.pi/360))*180/math.pi
    city_cursor=await svg.evaluate("""(svg, xy) => {
        const point = svg.createSVGPoint(); [point.x, point.y] = xy;
        const screen = point.matrixTransform(svg.getScreenCTM());
        return [screen.x, screen.y];
    }""",[-2,projected_y])
    await page.mouse.move(*(round(value) for value in city_cursor))
    leeds=page.locator('.city-label').filter(has_text='Leeds')
    manchester=page.locator('.city-label').filter(has_text='Manchester')
    for _ in range(8):
        if await leeds.is_visible() and await manchester.is_visible():
            break
        height=float((await svg.get_attribute('viewBox')).split()[3])
        await page.mouse.wheel(0,-160)
        await page.wait_for_function('(height) => document.querySelector(".overview-svg").viewBox.baseVal.height < height',arg=height)
    await expect(leeds).to_be_visible()
    await expect(manchester).to_be_visible()
    for label in [leeds,manchester]:
        assert await label.evaluate("""node => {
            const city = node.getBoundingClientRect(), map = node.closest('svg').getBoundingClientRect();
            return city.left >= map.left && city.right <= map.right && city.top >= map.top && city.bottom <= map.bottom;
        }"""), 'City label lies outside the visible map'


async def check_online_map(browser):
    # Serve the real vendored library and synthetic successful tiles; no OSM traffic.
    tile=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5xkAAAAASUVORK5CYII=')
    context=await browser.new_context(viewport={'width':1440,'height':1100},device_scale_factor=1)
    # Capture the real map in the test realm without modifying the library or its SRI.
    await context.add_init_script("""Object.defineProperty(window, 'L', {
        configurable: true,
        set(library) {
            const create = library.map;
            library.map = (...args) => (window.__birdingTestMap = create(...args));
            Object.defineProperty(window, 'L', {value: library, writable: true, configurable: true});
        }
    });""")
    tiles=[]
    async def online_handler(route):
        url=urlsplit(route.request.url)
        if url.hostname=='tile.openstreetmap.org':
            tiles.append(url.path)
            return await route.fulfill(body=tile,content_type='image/png')
        await handler(route)
    await context.route('**/*',online_handler)
    page=await context.new_page()
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    await show(page,'birding/')
    await expect(page.locator('#street-map')).to_be_visible()
    await expect(page.locator('#street-toggle')).to_have_attribute('aria-pressed','true')
    await page.wait_for_function('window.__birdingTestMap && document.querySelector(".leaflet-tile-loaded")')
    assert tiles, 'Default detailed map did not request tiles'
    assert await page.locator('.street-pin').count()==len([p for p in places if p['coordinates']])
    await page.locator('#street-map').scroll_into_view_if_needed()
    box=await page.locator('#street-map').bounding_box()
    await page.mouse.move(box['x']+box['width']*.4,box['y']+box['height']*.45)
    zoom=await page.evaluate('__birdingTestMap.getZoom()')
    await page.mouse.wheel(0,-240)
    await page.wait_for_function('(z) => __birdingTestMap.getZoom() > z',arg=zoom)
    await page.wait_for_function('!__birdingTestMap._animatingZoom')
    zoomed=await page.evaluate('__birdingTestMap.getZoom()')
    await page.mouse.wheel(0,240)
    await page.wait_for_function('(z) => __birdingTestMap.getZoom() < z',arg=zoomed)
    await page.wait_for_function('!__birdingTestMap._animatingZoom')
    # Frame the authored photo location, then preserve this viewport through both modes.
    lng,lat=photo_place['coordinates']['lng'],photo_place['coordinates']['lat']
    await page.evaluate('([lat,lng]) => __birdingTestMap.setView([lat,lng],11,{animate:false})',[lat,lng])
    view=await page.evaluate('({center:__birdingTestMap.getCenter(),zoom:__birdingTestMap.getZoom()})')
    await page.locator('.street-pin[title="'+photo_place['name']+'"]').click()
    await expect(page.locator('#detail-title')).to_have_text(photo_place['name'])
    await page.locator('.photo-open').first.click()
    assert await page.locator('#lightbox').evaluate('(d)=>d.open')
    await page.keyboard.press('Escape')
    await page.locator('#street-toggle').click()
    await expect(page.locator('#outline-map')).to_be_visible()
    await page.locator('#street-toggle').click()
    await expect(page.locator('#street-map')).to_be_visible()
    restored=await page.evaluate('({center:__birdingTestMap.getCenter(),zoom:__birdingTestMap.getZoom()})')
    assert abs(restored['zoom']-view['zoom'])<1e-8, (view,restored)
    assert all(abs(view['center'][key]-restored['center'][key])<.01 for key in ['lat','lng']), (view,restored)
    assert not errors,errors
    await context.close()
    return 'pass: local Leaflet, default detailed map, successful tiles, wheel zoom in/out, viewport preservation, markers and gallery'


async def main():
    result={'test_transport':'Chromium rendering with local filesystem route fulfilment; external requests blocked. Local HTTP server checked separately.'}
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.environ.get('BIRDING_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome'),headless=True,args=['--no-sandbox'])
        context=await browser.new_context(viewport={'width':1440,'height':1100},device_scale_factor=1)
        page=await context.new_page()
        errors=[]; requests=[]
        page.on('pageerror',lambda error: errors.append(str(error)))
        page.on('request',lambda request: requests.append(request.url))
        await context.route('**/*',handler)
        await show(page, 'birding/')
        await expect(page.locator('#map-status')).to_contain_text('unavailable')
        await expect(page.locator('#outline-map')).to_be_visible()
        await page.wait_for_selector('.map-point'); await page.wait_for_selector('#detail-title')
        await page.screenshot(path=str(OUT/'Birding_Map_Desktop.png'),full_page=True)
        result['initial_location']=await page.locator('#detail-title').inner_text()
        result['map_polygons']=await page.locator('.map-land').count()
        result['published_places']=len(places)
        result['initial_external_requests']=[r for r in requests if not r.startswith(BASE)]
        await expect(page.locator('#detail-title')).to_have_text(places[0]['name'])
        assert await page.locator('.filterbar, .places-section, .journal-note').count()==0
        assert await page.evaluate("getComputedStyle(document.body).backgroundColor==='rgb(238, 246, 251)' && [getComputedStyle(document.body).backgroundImage,getComputedStyle(document.body,'::before').backgroundImage].every(value=>value==='none')")
        await show(page, 'birding/', '#'+photo_place['id'])
        await expect(page.locator('#map-status')).to_contain_text('unavailable')
        await expect(page.locator('#detail-title')).to_have_text(photo_place['name'])
        await expect(page.locator('.photo-open')).to_have_count(photo_count)
        await select_overview_place(page,photo_place)
        await expect(page.locator('#detail-title')).to_be_focused()
        await page.locator('.photo-open').first.click()
        assert await page.locator('#lightbox').evaluate('(d)=>d.open')
        await page.keyboard.press('Escape')
        assert not await page.locator('#lightbox').evaluate('(d)=>d.open')
        await page.locator('#tab-notes').click()
        assert await page.locator('#panel-notes').is_visible()
        await page.keyboard.press('ArrowLeft')
        assert await page.locator('#panel-photos').is_visible()
        await page.locator('#reset-view').click()
        await page.screenshot(path=str(OUT/'Birding_Map_Desktop.png'),full_page=True)
        before=await page.locator('.overview-svg').get_attribute('viewBox')
        await page.locator('#zoom-in').click()
        after=await page.locator('.overview-svg').get_attribute('viewBox')
        assert before!=after
        await page.locator('#reset-view').click()
        await check_overview_wheel(page)
        await check_city_labels(page)
        await page.locator('#street-toggle').click()
        await expect(page.locator('#map-status')).to_contain_text('unavailable')
        assert await page.locator('#outline-map').is_visible()
        result['desktop_interactions']='pass: solid pale blue background, simplified layout, clustered map selection, tabs, lightbox, deep link, wheel anchor, city labels, automatic online failure fallback'
        result['page_errors']=errors
        await show(page, '')
        assert await page.locator('.birding-entry').count()==1
        await page.locator('.birding-entry').scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT/'Homepage_Birding_Entry.png'),full_page=False)
        mobile=await browser.new_context(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True)
        await mobile.route('**/*',handler)
        mp=await mobile.new_page(); merr=[]; mp.on('pageerror',lambda err:merr.append(str(err)))
        await show(mp, 'birding/', '#'+photo_place['id'])
        await expect(mp.locator('#map-status')).to_contain_text('unavailable')
        await mp.wait_for_selector('.map-point')
        assert await mp.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        await mp.screenshot(path=str(OUT/'Birding_Map_Mobile.png'),full_page=True)
        await select_overview_place(mp,photo_place)
        await expect(mp.locator('#detail-title')).to_have_text(photo_place['name'])
        await mp.locator('.photo-open').first.click()
        assert await mp.locator('#lightbox').evaluate('(d)=>d.open')
        await mp.locator('#lightbox-close').click()
        result['mobile']='pass: 390 px layout, no horizontal overflow, location selection, modal'
        result['mobile_errors']=merr
        noscript=await browser.new_context(java_script_enabled=False,viewport={'width':390,'height':844})
        await noscript.route('**/*',handler)
        np=await noscript.new_page()
        await show(np, 'birding/catalogue.html')
        assert await np.locator('article').count()==len(places)
        assert await np.locator('.catalogue-photo').count()==sum(len(all_photos(place)) for place in places)
        result['no_javascript_catalogue']='pass'
        result['online_interactions']=await check_online_map(browser)
        assert not errors, errors
        assert not merr, merr
        await browser.close()
    (OUT/'browser-test-results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

asyncio.run(main())
