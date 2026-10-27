import { t } from '../../lib/i18n';
import { useSpaLink } from '../../lib/spaLink';
import { Skeleton } from '../../ui';
import { PredictInline } from './PredictForm';
import { usePredictMatches } from './usePredict';
import './predict.css';

/**
 * Блок «Твой прогноз» на главной (ленивый чанк): компактный ввод счёта на ближайший матч.
 * Нет данных прогнозов (503, сеть) — прежняя карточка-ссылка в раздел, главная не ломается.
 */
export default function HomePredict() {
  const link = useSpaLink();
  const { state, reload, setMyPrediction } = usePredictMatches();
  if (state.kind === 'loading') return <Skeleton height={148} radius={24} className="hp-skel" />;
  const next = state.kind === 'ok' ? state.data.next : null;
  if (!next) {
    return (
      <a className="ui-card home-predict" {...link('/predict')}>
        <span className="home-predict__head">
          <span className="home-predict__title">{t('Прогнозы')}</span>
          <span className="home-predict__aside">{t('рейтинг болельщиков')}</span>
        </span>
        <span className="home-predict__row">
          <span className="home-predict__cta">{t('Угадывай счёт матчей Реала')}</span>
          <svg className="home-predict__chev" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </span>
      </a>
    );
  }
  return <PredictInline match={next} onSaved={setMyPrediction} onClosed={reload} more={link('/predict')} />;
}
