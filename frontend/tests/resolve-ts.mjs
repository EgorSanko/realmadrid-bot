// Тесты (node --test) грузят исходники src как есть; в src импорты без расширения (так принято у Vite).
// Подставляем .ts / /index.ts, когда путь без расширения не нашёлся.
import { registerHooks } from 'node:module';

registerHooks({
  resolve(spec, ctx, next) {
    try {
      return next(spec, ctx);
    } catch (e) {
      if (!spec.startsWith('.') || /\.[cm]?[jt]sx?$|\.json$/.test(spec)) throw e;
      for (const ext of ['.ts', '/index.ts']) {
        try {
          return next(spec + ext, ctx);
        } catch {
          /* следующий вариант */
        }
      }
      throw e;
    }
  },
});
