import type { StreamState } from '../lib/stream';
import { isNativeApp } from '../lib/shell';
import { t } from '../lib/i18n';
import { Player } from './Player';

/**
 * Блок трансляции на главной: плеер, пока эфир включён, иначе — заглушка из a-home.html.
 * В приложении из RuStore блока нет совсем (ни плеера, ни заглушки; hls.js не грузится).
 */
export function StreamBlock({ stream }: { stream: StreamState | null }) {
  if (isNativeApp()) return null;
  if (stream?.live && stream.url) {
    return (
      <section className="stream" aria-label={t('Трансляция')}>
        <Player key={stream.url} src={stream.url} title={stream.title} />
        {stream.title && <p className="stream__title">{stream.title}</p>}
      </section>
    );
  }
  return (
    <section className="stream-empty" aria-label={t('Трансляция')}>
      <div className="stream-empty__icon">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8 5v14l11-7z" />
        </svg>
      </div>
      <p className="stream-empty__title">{t('Трансляция появится здесь')}</p>
      <p className="stream-empty__text">{t('Эфир включится перед стартовым свистком')}</p>
    </section>
  );
}
