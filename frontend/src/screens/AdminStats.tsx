import { useEffect, useState } from 'react';
import { AuthFetchError, authFetch } from '../lib/auth';

/*
 * «Статистика» в админке: сколько людей приходит (GET /api/admin/stats, backend/app/visits.py).
 * Люди — устройства с анонимным id (сайт, мини-апп, приложение), «с входом» — пользователи Telegram.
 * Дни — по Москве. Только настоящие числа: пока данных нет — нули.
 */

type Platform = 'tg' | 'android' | 'web';
type ByPlatform = Record<Platform, number>;

interface StatsDay {
  day: string;
  new_visitors: number;
  active_visitors: number;
  new_users: number;
  new_by_platform: ByPlatform;
  active_by_platform: ByPlatform;
}

export interface AdminStatsResponse {
  today: string;
  tz: string;
  platforms: Platform[];
  days: StatsDay[];
  totals: {
    visitors: number;
    visitors_by_platform: ByPlatform;
    users: number;
    linked_visitors: number;
    new_1d: number;
    new_7d: number;
    new_30d: number;
    new_users_1d: number;
    new_users_7d: number;
    new_users_30d: number;
    active_1d: number;
    active_7d: number;
    active_30d: number;
  };
}

const PLATFORMS: { key: Platform; label: string }[] = [
  { key: 'web', label: 'Сайт' },
  { key: 'tg', label: 'Telegram' },
  { key: 'android', label: 'Android' },
];

const nf = new Intl.NumberFormat('ru-RU');
const fmt = (n: number) => nf.format(n);

/** '2026-10-20' → '20.10' */
const short = (day: string) => `${day.slice(8, 10)}.${day.slice(5, 7)}`;

const W = 300;
const H = 120;

function Chart({ days }: { days: StatsDay[] }) {
  const max = Math.max(1, ...days.map((d) => d.new_visitors));
  const slot = W / days.length;
  const bar = Math.max(2, slot - 2);
  return (
    <svg className="ast-chart" viewBox={`0 0 ${W} ${H + 14}`} role="img" aria-label="Новые люди по дням за 30 дней">
      <line x1="0" y1={H + 0.5} x2={W} y2={H + 0.5} className="ast-axis" />
      {days.map((d, i) => {
        let y = H;
        const x = i * slot + (slot - bar) / 2;
        return (
          <g key={d.day}>
            <title>{`${short(d.day)}: ${d.new_visitors} нов.${PLATFORMS.map((p) => ` · ${p.label} ${d.new_by_platform[p.key]}`).join('')}`}</title>
            {PLATFORMS.map((p) => {
              const h = (d.new_by_platform[p.key] / max) * (H - 4);
              if (h <= 0) return null;
              y -= h;
              return <rect key={p.key} x={x} y={y} width={bar} height={h} rx="1" className={`ast-bar ast-bar--${p.key}`} />;
            })}
          </g>
        );
      })}
      <text x="0" y={H + 12} className="ast-tick">
        {short(days[0].day)}
      </text>
      <text x={W} y={H + 12} className="ast-tick" textAnchor="end">
        {short(days[days.length - 1].day)}
      </text>
      <text x={W} y="9" className="ast-tick" textAnchor="end">
        макс. {fmt(max)}
      </text>
    </svg>
  );
}

/** Секция статистики. canFetch — есть вход админа через Telegram (по админ-токену статистика не отдаётся). */
export function AdminStats({ canFetch }: { canFetch: boolean }) {
  const [data, setData] = useState<AdminStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!canFetch) return;
    const ctl = new AbortController();
    authFetch<AdminStatsResponse>('/api/admin/stats', { signal: ctl.signal })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if ((e as Error).name === 'AbortError') return;
        setError(e instanceof AuthFetchError ? e.message : 'Не удалось загрузить статистику');
      });
    return () => ctl.abort();
  }, [canFetch]);

  if (!canFetch) {
    return (
      <section className="admin-card ast" aria-label="Статистика">
        <h2 className="ast-title">Статистика</h2>
        <p className="admin-hint">Статистика доступна после входа владельца через Telegram.</p>
      </section>
    );
  }

  if (!data) {
    return (
      <section className="admin-card ast" aria-label="Статистика" aria-busy={!error}>
        <h2 className="ast-title">Статистика</h2>
        {error ? (
          <p className="admin-msg admin-msg--err" role="alert">
            {error}
          </p>
        ) : (
          <p className="admin-hint">Загружаем…</p>
        )}
      </section>
    );
  }

  const t = data.totals;
  const rows = [...data.days].reverse();
  return (
    <section className="admin-card ast" aria-label="Статистика">
      <h2 className="ast-title">Статистика</h2>
      <p className="admin-hint">Новые люди — первое открытие на устройстве (сайт, мини-апп, приложение). Дни по Москве.</p>

      <div className="ast-nums">
        <div className="ast-num ast-num--hero">
          <b>{fmt(t.new_1d)}</b>
          <span>новых сегодня</span>
        </div>
        <div className="ast-num">
          <b>{fmt(t.new_7d)}</b>
          <span>за 7 дней</span>
        </div>
        <div className="ast-num">
          <b>{fmt(t.new_30d)}</b>
          <span>за 30 дней</span>
        </div>
        <div className="ast-num">
          <b>{fmt(t.visitors)}</b>
          <span>всего людей</span>
        </div>
        <div className="ast-num">
          <b>{fmt(t.users)}</b>
          <span>всего с входом</span>
        </div>
        <div className="ast-num">
          <b>{fmt(t.active_1d)}</b>
          <span>
            были сегодня · 7 дн. {fmt(t.active_7d)} · 30 дн. {fmt(t.active_30d)}
          </span>
        </div>
      </div>

      <Chart days={data.days} />
      <ul className="ast-legend">
        {PLATFORMS.map((p) => (
          <li key={p.key}>
            <i className={`ast-dot ast-bar--${p.key}`} aria-hidden="true" />
            {p.label} <span className="muted">· всего {fmt(t.visitors_by_platform[p.key])}</span>
          </li>
        ))}
      </ul>

      <div className="ast-table-wrap">
        <table className="ast-table">
          <thead>
            <tr>
              <th scope="col">День</th>
              <th scope="col">Новые</th>
              <th scope="col">Были</th>
              <th scope="col">Вошли впервые</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.day}>
                <th scope="row">{short(d.day)}</th>
                <td>{fmt(d.new_visitors)}</td>
                <td>{fmt(d.active_visitors)}</td>
                <td>{fmt(d.new_users)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
