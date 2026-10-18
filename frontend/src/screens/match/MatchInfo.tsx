import { useId, useState } from 'react';
import type { ApiMatch } from '../../api/match';
import { Card, Flag, PlayerPhoto, useInViewOnce } from '../../ui';
import { cx } from '../../ui/format';
import { infoLine, refereeView, stadiumView, weatherView, type RefScaleView, type RefereeView, type StadiumView, type WeatherIcon, type WeatherView } from './info';
import { aboutRows } from './view';
import './info.css';

/**
 * «О матче»: стадион (+ погода) и судья. Полные карточки — когда FotMob дал подробности
 * (вместимость, погоду, статистику судьи); иначе — прежние строки «Стадион / Зрители / Судья».
 * compact — лайв: одна строка «Bernabéu · 10° · Busquets Ferrer», по нажатию раскрывается.
 */
export function MatchInfo({ match, compact }: { match: ApiMatch; compact?: boolean }) {
  const st = stadiumView(match);
  const w = weatherView(match);
  const ref = refereeView(match);
  const rich = !!(w || st?.capacity || st?.surface || ref?.yellow || ref?.fouls || ref?.matches);
  const [open, setOpen] = useState(false);
  const bodyId = useId();

  if (!rich) {
    const rows = aboutRows(match);
    if (!rows.length) return null;
    return (
      <Card ariaLabel="О матче" className="mt-about">
        {rows.map(([k, v, iso]) => (
          <div key={k} className="mt-about__row">
            <span className="mt-about__k">{k}</span>
            <span className="mt-about__v">
              {iso && <Flag iso2={iso} name="" width={20} />}
              <span>{v}</span>
            </span>
          </div>
        ))}
      </Card>
    );
  }

  const cards = (
    <>
      {st && <StadiumCard st={st} w={w} />}
      {ref && <RefereeCard r={ref} />}
    </>
  );
  if (!compact) return cards;

  const line = infoLine(match);
  return (
    <>
      <button
        type="button"
        className={cx('ui-card mi-fold', open && 'is-open')}
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="mi-fold__cap">О матче</span>
        <span className="mi-fold__line">{line}</span>
        <svg className="mi-fold__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div id={bodyId} className="mi-fold__body">
          {cards}
        </div>
      )}
    </>
  );
}

function StadiumCard({ st, w }: { st: StadiumView; w: WeatherView | null }) {
  const tiles = [
    st.capacity && { k: 'Вместимость', v: st.capacity },
    st.surface && { k: 'Покрытие', v: st.surface },
    st.attendance && { k: 'Зрители', v: st.attendance },
  ].filter((x): x is { k: string; v: string } => !!x);
  const place = [st.city, st.country].filter(Boolean).join(', ');
  return (
    <Card ariaLabel="Стадион" className="mi">
      <h2 className="mt-h2">Стадион</h2>
      <p className="mi-title">{st.name}</p>
      {place && (
        <p className="mi-place">
          {st.iso && <Flag iso2={st.iso} name="" width={18} />}
          <span>{place}</span>
        </p>
      )}
      {tiles.length > 0 && (
        <div className="mi-tiles" style={{ gridTemplateColumns: `repeat(${tiles.length}, minmax(0, 1fr))` }}>
          {tiles.map((t) => (
            <div key={t.k} className="mi-tile">
              <span className="mi-tile__k">{t.k}</span>
              <span className="mi-tile__v">{t.v}</span>
            </div>
          ))}
        </div>
      )}
      {w && (
        <div className="mi-weather">
          <WeatherGlyph kind={w.icon} />
          <div className="mi-weather__body">
            <p className="mi-weather__main">
              {w.temp}
              {w.text && <> · {w.text}</>}
            </p>
            {w.details && <p className="mi-weather__sub">{w.details}</p>}
          </div>
        </div>
      )}
    </Card>
  );
}

function RefereeCard({ r }: { r: RefereeView }) {
  const meta = [r.country, r.matches].filter(Boolean).join(' · ');
  return (
    <Card ariaLabel="Судья" className="mi">
      <h2 className="mt-h2">Судья</h2>
      <div className="mi-ref">
        <PlayerPhoto id={r.id} name={r.name} size={52} className="mi-ref__photo" />
        <div className="mi-ref__body">
          <p className="mi-ref__name">{r.name}</p>
          {meta && (
            <p className="mi-ref__meta">
              {r.iso && <Flag iso2={r.iso} name="" width={18} />}
              <span>{meta}</span>
            </p>
          )}
        </div>
      </div>
      {r.yellow && <RefScale title="Жёлтые карточки" s={r.yellow} />}
      {r.fouls && <RefScale title="Фолы" s={r.fouls} />}
      {r.tiles.length > 0 && (
        <div className="mi-tiles" style={{ gridTemplateColumns: `repeat(${r.tiles.length}, minmax(0, 1fr))` }}>
          {r.tiles.map((t) => (
            <div key={t.label} className="mi-tile">
              <span className="mi-tile__k">{t.label}</span>
              <span className="mi-tile__v">{t.value}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function RefScale({ title, s }: { title: string; s: RefScaleView }) {
  const [ref, seen] = useInViewOnce<HTMLDivElement>(0.5);
  return (
    <div ref={ref} className={cx('mi-scale', 'mo-reveal', seen && 'is-in')}>
      <div className="mi-scale__row">
        <span className="mi-scale__title">{title}</span>
        <span className="mi-scale__val">
          <b>{s.value}</b> / матч
        </span>
      </div>
      <div className={cx('mi-bar', s.level === 'above' && 'mi-bar--hot')} aria-hidden="true">
        <span className="mi-bar__fill" style={{ width: `${s.fill}%` }} />
        {s.avgFill != null && <span className="mi-bar__avg" style={{ left: `${s.avgFill}%` }} />}
      </div>
      <div className="mi-scale__row mi-scale__row--sub">
        <span>{s.avg ? `в среднем по лиге ${s.avg}` : ''}</span>
        {s.label && <span className={cx('mi-level', s.level && `mi-level--${s.level}`)}>{s.label}</span>}
      </div>
    </div>
  );
}

/** Значок погоды — линейная иконка в стиле набора (stroke 1.6, золото для солнца). */
export function WeatherGlyph({ kind }: { kind: WeatherIcon }) {
  const sun = (
    <g className="mi-wx__sun">
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" />
    </g>
  );
  const cloud = <path d="M7.5 18.5h9.2a3.8 3.8 0 0 0 .4-7.6 5.3 5.3 0 0 0-10.2 1.3A3.2 3.2 0 0 0 7.5 18.5z" />;
  let body;
  switch (kind) {
    case 'clear':
      body = sun;
      break;
    case 'partly':
      body = (
        <>
          <g className="mi-wx__sun" transform="translate(-3.5 -3.5) scale(.75)">
            <circle cx="12" cy="12" r="4.2" />
            <path d="M12 3v2M3 12h2M5.6 5.6l1.4 1.4M17 7l1.4-1.4" />
          </g>
          <path d="M9 20h8.2a3.4 3.4 0 0 0 .3-6.8 4.8 4.8 0 0 0-9.2 1.2A2.9 2.9 0 0 0 9 20z" />
        </>
      );
      break;
    case 'rain':
      body = (
        <>
          <path d="M7.5 15.5h9.2a3.8 3.8 0 0 0 .4-7.6 5.3 5.3 0 0 0-10.2 1.3A3.2 3.2 0 0 0 7.5 15.5z" />
          <path d="M9 18l-1 2.5M13 18l-1 2.5M17 18l-1 2.5" />
        </>
      );
      break;
    case 'storm':
      body = (
        <>
          <path d="M7.5 15h9.2a3.8 3.8 0 0 0 .4-7.6 5.3 5.3 0 0 0-10.2 1.3A3.2 3.2 0 0 0 7.5 15z" />
          <path className="mi-wx__bolt" d="M12.5 15.5l-2 3.5h3l-2 3.5" />
        </>
      );
      break;
    case 'snow':
      body = (
        <>
          <path d="M7.5 15h9.2a3.8 3.8 0 0 0 .4-7.6 5.3 5.3 0 0 0-10.2 1.3A3.2 3.2 0 0 0 7.5 15z" />
          <path d="M9 18.5h.01M12 20h.01M15 18.5h.01" strokeWidth="2.4" />
        </>
      );
      break;
    case 'fog':
      body = <path d="M4 9h16M6 13h12M4 17h16" />;
      break;
    case 'wind':
      body = <path d="M3 9h11a3 3 0 1 0-3-3M3 13h15a3 3 0 1 1-3 3M3 17h7" />;
      break;
    default:
      body = cloud;
  }
  return (
    <svg className="mi-wx" viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {body}
    </svg>
  );
}
