import { initTelegram } from './telegram';
import { telegramInitData } from './lib/auth';
import { applyLang, detectLang } from './lib/i18n';

// После выкладки старые чанки удаляются: вкладка (или мини-апп), открытая до неё, не найдёт ленивый чанк
// экрана и показала бы пустоту. Перезагружаемся на свежий index.html — не чаще раза в 30 с, без петли.
window.addEventListener('vite:preloadError', (e) => {
  let last = 0;
  try {
    last = Number(sessionStorage.getItem('rmChunkReload') || 0);
    sessionStorage.setItem('rmChunkReload', String(Date.now()));
  } catch {
    return;
  }
  if (Date.now() - last < 30_000) return;
  e.preventDefault();
  window.location.reload();
});

// Язык — до загрузки приложения: тексты в константах модулей переводятся при их импорте.
// Английский словарь — отдельным чанком, русским он не грузится.
async function main() {
  const inTelegram = await initTelegram();
  const l = detectLang(telegramInitData());
  applyLang(l, l === 'en' ? (await import('./i18n/en')).default : {});
  const { start } = await import('./boot');
  await start(inTelegram);
}

void main();
