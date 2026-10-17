/** Показ кода входа (components/CodeLogin.tsx). Без зависимостей — проверяется node --test. */

/** «123456» → «123 456» — так легче прочитать и переписать. */
export function spacedCode(code: string): string {
  return code.length === 6 ? `${code.slice(0, 3)} ${code.slice(3)}` : code;
}

/** Остаток в «м:сс». */
export function countdown(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
