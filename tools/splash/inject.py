"""Собирает заставку и вставляет её в frontend/index.html между маркерами.

  python tools/splash/build.py && python tools/splash/inject.py

Источник эмблемы — logo.svg (4 контура), слои режет build.py, анимация — splash.css.
"""
import pathlib, re

HERE = pathlib.Path(__file__).parent
INDEX = HERE.parent.parent / "frontend" / "index.html"
svg = (HERE / "crest-anim.svg").read_text(encoding="utf-8")
css = (HERE / "splash.css").read_text(encoding="utf-8")
css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
css = re.sub(r"\s*\n\s*", "", css)

SCRIPT = """(function(){var s=document.getElementById('splash');if(!s)return;
var seen=false;try{seen=sessionStorage.getItem('rmSplash')==='1';sessionStorage.setItem('rmSplash','1')}catch(e){}
if(seen){s.remove();return}
if(!/tgWebApp/.test(location.hash+location.search)&&window.matchMedia&&matchMedia('(min-width: 1024px)').matches){s.remove();return}
var rm=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches,minT=rm?600:2900,t0=Date.now(),done=false;
function hide(){if(done)return;done=true;s.classList.add('sp-out');setTimeout(function(){s.remove()},500)}
function tick(){var el=document.getElementById('root'),ready=el&&el.childElementCount>0,dt=Date.now()-t0;
if((ready&&dt>=minT)||dt>7000)hide();else setTimeout(tick,100)}
s.addEventListener('click',hide);tick()})();"""

block = (f'<!-- splash:start (генерируется tools/splash/inject.py) -->\n'
         f'    <style>{css}</style>\n'
         f'    <div id="splash" aria-hidden="true">{svg}<div class="sp-word">МАДРИДИСТА</div><div class="sp-line"></div></div>\n'
         f'    <script>{SCRIPT}</script>\n'
         f'    <!-- splash:end -->')
html = INDEX.read_text(encoding="utf-8")
if "<!-- splash:start" in html:
    html = re.sub(r"<!-- splash:start.*?<!-- splash:end -->", lambda m: block, html, flags=re.S)
else:
    html = html.replace('<div id="root"></div>', block + '\n    <div id="root"></div>')
INDEX.write_text(html, encoding="utf-8")
print("index.html:", len(html), "байт")
