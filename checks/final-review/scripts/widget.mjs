// Как telegram-widget.js исполняет data-onauth (нужен ли CSP 'unsafe-eval') и какие хосты он трогает.
const r = await fetch('https://telegram.org/js/telegram-widget.js?22');
const s = await r.text();
console.log('status', r.status, 'len', s.length);
for (const re of [/new Function[^;]{0,80}/g, /eval\([^;]{0,60}/g, /onauth[^;]{0,100}/gi, /https?:\/\/[a-z.]+telegram[a-z.]*/g]) {
  console.log(re, [...new Set(s.match(re) || [])].slice(0, 6));
}
