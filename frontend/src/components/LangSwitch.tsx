import { lang, setLang, t, type Lang } from '../lib/i18n';
import { cx } from '../ui/format';
import './langSwitch.css';

const ITEMS: Array<{ id: Lang; label: string; name: string }> = [
  { id: 'ru', label: 'RU', name: 'Русский' },
  { id: 'en', label: 'EN', name: 'English' },
];

/** Переключатель языка RU / EN: выбор запоминается, страница перезагружается на новом языке. */
export function LangSwitch({ className }: { className?: string }) {
  const cur = lang();
  return (
    <div className={cx('lang-sw', className)} role="group" aria-label={t('Язык')}>
      {ITEMS.map((it) => (
        <button
          key={it.id}
          type="button"
          className={cx('lang-sw__btn', it.id === cur && 'on')}
          aria-pressed={it.id === cur}
          title={it.name}
          lang={it.id}
          onClick={() => it.id !== cur && setLang(it.id)}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}
