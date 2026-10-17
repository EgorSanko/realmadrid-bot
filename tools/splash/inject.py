"""Собирает заставку и вставляет её в frontend/index.html между маркерами.

  python tools/splash/build.py && python tools/splash/inject.py

Источник эмблемы — logo.svg (4 контура), слои режет build.py, анимация — splash.css, уход — SCRIPT ниже.

CSP: скрипт инлайновый, nginx пускает его по sha256. Хэш руками не правится: deploy/deploy.sh после
npm run build считает его из dist/index.html (deploy/csp-hashes.mjs) и подставляет в nginx.conf.template.
"""
import pathlib, re

HERE = pathlib.Path(__file__).parent
INDEX = HERE.parent.parent / "frontend" / "index.html"
svg = (HERE / "crest-anim.svg").read_text(encoding="utf-8")
css = (HERE / "splash.css").read_text(encoding="utf-8")
css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
css = re.sub(r"\s*\n\s*", "", css)

# Заставка показывается один раз за сессию: на телефоне, в Telegram Mini App и в приложении из RuStore.
# Когда эмблема собралась (BUILD мс) и React нарисовал страницу, на главной эмблема перелетает на место
# img.brand__crest в шапке (FLIP: transform translate+scale), фон растворяется; в конце заставка убирается,
# а картинка шапки, скрытая на время полёта, показывается в том же кадре — подмены не видно.
# Не главная (или картинки шапки нет) — просто растворение. React не готов за CAP мс — уходим всё равно.
# Тап: во время сборки — сразу к уходу, во время полёта — сразу в конец.
# Геометрия: эмблема в svg занимает 0..32 × 0..43 во viewBox -1 -1 34 45; в PNG шапки — её непрозрачная
# область (меряем по альфе на canvas; не вышло — запасные доли FB для /img/team/8633.png 192×192).
SCRIPT = """(function(){var s=document.getElementById('splash');if(!s)return;
var seen=false;try{seen=sessionStorage.getItem('rmSplash')==='1';sessionStorage.setItem('rmSplash','1')}catch(e){}
if(seen){s.remove();return}
var mm=function(q){return window.matchMedia&&matchMedia(q).matches};
if(!/tgWebApp/.test(location.hash+location.search)&&!/MadridistaApp\\/\\d/.test(navigator.userAgent)&&mm('(min-width: 1024px)')){s.remove();return}
var rm=mm('(prefers-reduced-motion: reduce)'),BUILD=rm?400:2300,CAP=7000,FLY=760,t0=Date.now(),stage=0,img=null,fl=[],cur=null,IB=null,fix=0,rt=0;
var crest=s.querySelector('.sp-crest'),FB=[27/192,4/192,167/192,190/192];
function end(){if(stage>2)return;stage=3;if(img)img.style.visibility='';s.remove()}
function fade(){s.classList.add('sp-out');setTimeout(end,rm?300:500)}
function settle(){s.style.animation='none';if(!s.getAnimations)return;
s.getAnimations({subtree:true}).forEach(function(a){try{a.finish()}catch(e){}})}
function target(){var i=document.querySelector('.brand__crest');if(!i)return null;var r=i.getBoundingClientRect();
return r.width>4&&r.bottom>0&&r.top<innerHeight?i:null}
function loaded(i){return i.complete&&i.naturalWidth>0}
function box(i){var w=i.naturalWidth,h=i.naturalHeight;
if(!IB){IB=FB;try{var c=document.createElement('canvas');c.width=w;c.height=h;var g=c.getContext('2d');g.drawImage(i,0,0);
var d=g.getImageData(0,0,w,h).data,x0=w,y0=h,x1=-1,y1=-1,x,y;
for(y=0;y<h;y++)for(x=0;x<w;x++)if(d[(y*w+x)*4+3]>=128){if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y}
if(x1>x0&&y1>y0)IB=[x0/w,y0/h,(x1+1)/w,(y1+1)/h]}catch(e){}}
var T=i.getBoundingClientRect(),k=Math.min(T.width/w,T.height/h),ox=T.left+(T.width-w*k)/2,oy=T.top+(T.height-h*k)/2;
return [ox+IB[0]*w*k,oy+IB[1]*h*k,ox+IB[2]*w*k,oy+IB[3]*h*k]}
function flip(){var B=box(img),t=crest.style.transform;crest.style.transform='none';var R=crest.getBoundingClientRect();crest.style.transform=t;
var k=Math.min(R.width/34,R.height/45),cx=(R.width-34*k)/2+17*k,cy=(R.height-45*k)/2+22.5*k,
sc=((B[2]-B[0])/(32*k)+(B[3]-B[1])/(43*k))/2;
return [(B[0]+B[2])/2-R.left-sc*cx,(B[1]+B[3])/2-R.top-sc*cy,sc,R.width]}
function tf(v){return 'translate('+v[0]+'px,'+v[1]+'px) scale('+v[2]+')'}
function land(){if(stage!==2)return;
if(!document.contains(img)||!loaded(img)){img.style.visibility='';img=null;stage=1;return fade()}
var v=flip();
if(fix++>2||Math.abs(v[0]-cur[0])<.3&&Math.abs(v[1]-cur[1])<.3&&Math.abs(v[2]-cur[2])*v[3]<.3)return end();
var a=crest.animate([{transform:tf(cur)},{transform:tf(v)}],{duration:180,easing:'ease-out'});
cur=v;crest.style.transform=tf(v);fl=[a];a.onfinish=a.oncancel=land}
function fly(){if(stage!==1)return;stage=2;img.style.visibility='hidden';s.classList.add('sp-fly');
cur=flip();crest.style.willChange='transform';crest.style.transform=tf(cur);
var a=crest.animate([{transform:'none'},{transform:tf(cur)}],{duration:FLY,easing:'cubic-bezier(.6,0,.18,1)'});
fl=[a,s.querySelector('.sp-bg').animate([{opacity:1},{opacity:0}],{duration:FLY-120,delay:80,easing:'cubic-bezier(.4,0,.6,1)',fill:'forwards'})];
[].forEach.call(s.querySelectorAll('.sp-word,.sp-line'),function(e){
fl.push(e.animate([{opacity:1,transform:'none'},{opacity:0,transform:'translateY(6px)'}],{duration:240,easing:'ease-out',fill:'forwards'}))});
a.onfinish=a.oncancel=land}
function leave(){if(stage)return;stage=1;settle();
var i=rm?null:target();if(i&&loaded(i)&&crest.animate){img=i;i.decode?i.decode().then(fly,fly):fly()}else fade()}
function tick(){if(stage)return;var now=Date.now(),dt=now-t0;if(dt>=CAP)return leave();
var root=document.getElementById('root'),i;if(root&&root.childElementCount&&!rt)rt=now;
var wait=location.pathname==='/'&&!rm&&!document.documentElement.classList.contains('desk')&&now-rt<1500;
if(dt<BUILD||!rt||(wait&&!((i=target())&&i.complete)))return setTimeout(tick,60);
requestAnimationFrame(function(){requestAnimationFrame(leave)})}
s.addEventListener('click',function(){if(!stage)leave();else if(stage===2)fl.forEach(function(a){try{a.finish()}catch(e){}})});
tick()})();"""

block = (f'<!-- splash:start (генерируется tools/splash/inject.py) -->\n'
         f'    <style>{css}</style>\n'
         f'    <div id="splash" aria-hidden="true"><div class="sp-bg"></div>{svg}<div class="sp-word">МАДРИДИСТА</div><div class="sp-line"></div></div>\n'
         f'    <script>{SCRIPT}</script>\n'
         f'    <!-- splash:end -->')
html = INDEX.read_text(encoding="utf-8")
if "<!-- splash:start" in html:
    html = re.sub(r"<!-- splash:start.*?<!-- splash:end -->", lambda m: block, html, flags=re.S)
else:
    html = html.replace('<div id="root"></div>', block + '\n    <div id="root"></div>')
INDEX.write_text(html, encoding="utf-8", newline="\n")  # LF, как в git: иначе на Windows CRLF и другой хэш CSP
print("index.html:", len(html), "байт")
