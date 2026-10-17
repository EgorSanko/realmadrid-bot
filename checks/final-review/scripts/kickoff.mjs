// Время ближайшего матча: UTC из API → МСК (сверка с «22:00 МСК» на главной).
const j = await (await fetch('https://realmadridfan.ru/api/home')).json();
const k = j.next?.kickoff;
console.log('next', j.next?.home?.name, '—', j.next?.away?.name, k,
  '→ МСК', new Date(k).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', weekday: 'short', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }));
