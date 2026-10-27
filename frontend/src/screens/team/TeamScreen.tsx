import { useEffect, useMemo, useState } from 'react';
import { usePlayerLinks } from '../../lib/playerNav';
import { useDesktop } from '../../lib/shell';
import { Badge, Card, ErrorState, Flag, PlayerPhoto, PlayerTap, SectionHeader, Skeleton, TeamCrest, type PlayerLinkProps } from '../../ui';
import { formatTime } from '../../ui/format';
import { errorText, useApiResource } from '../../lib/apiResource';
import { isEn, t, tc } from '../../lib/i18n';
import {
  LINES,
  ageText,
  feeText,
  flagIso,
  plural,
  positionRu,
  returnInfo,
  seasonLabel,
  type Injury,
  type Leader,
  type LineKey,
  type SquadPlayer,
  type TeamResponse,
  type Transfer,
} from './teamData';
import './team.css';

/** Этап 8: «Команда» по design/screens/a-team.html. Данные — /api/team (снимок сборщика). */
export default function TeamScreen() {
  useEffect(() => {
    document.title = t('Состав «Реала», лазарет и трансферы — Мадридиста');
  }, []);
  const { data, error, loading, reload } = useApiResource<TeamResponse>('/api/team');

  return (
    <main className="tm">
      <header className="topbar">
        <h1 className="topbar__title">{t('Команда')}</h1>
        <span className="tm-season">{t('сезон {season}', { season: seasonLabel() })}</span>
      </header>
      {data ? (
        <TeamBody team={data} />
      ) : loading ? (
        <TeamSkeleton />
      ) : (
        <Card>
          <ErrorState plain text={errorText(error)} onRetry={reload} />
        </Card>
      )}
    </main>
  );
}

function TeamSkeleton() {
  return (
    <div aria-busy="true">
      <div className="tm-leaders">
        {[0, 1, 2].map((i) => (
          <Card key={i} inset={false} className="tm-leader">
            <Skeleton width={50} height={12} />
            <Skeleton width={36} height={26} style={{ marginTop: 8 }} />
            <Skeleton width="80%" height={12} style={{ marginTop: 8 }} />
          </Card>
        ))}
      </div>
      <Card>
        <Skeleton width={110} height={18} />
        <Skeleton shape="list" rows={3} style={{ marginTop: 8 }} />
      </Card>
      <Card>
        <Skeleton width={90} height={18} />
        <Skeleton shape="list" rows={6} style={{ marginTop: 8 }} />
      </Card>
    </div>
  );
}

function TeamBody({ team }: { team: TeamResponse }) {
  const desktop = useDesktop();
  const has = (k: string) => team.available.includes(k);
  const injuries = team.injuries ?? [];
  // дисквалификации и травмы из лазарета — для бейджа в составе (кроме тех, кто уже тренируется)
  const outById = useMemo(() => {
    const m = new Map<number, Injury>();
    for (const i of injuries) {
      const r = returnInfo(i.expected_return);
      if (!r.back && !r.past) m.set(i.id, i);
    }
    return m;
  }, [injuries]);

  // сайт на компьютере: состав — сетка карточек с фото; лидеры и лазарет — сбоку
  if (desktop) {
    return (
      <>
        {team.stale && (
          <p className="tm-stale" role="status">
            {t('Данные могли устареть · обновлено в {time} МСК', { time: formatTime(team.updated_at) })}
          </p>
        )}
        <div className="dk-split tm-desk">
          <div className="dk-col">
            {has('squad') && team.squad && <SquadGrid team={team} outById={outById} />}
            {has('transfers') && team.transfers && <Transfers transfers={team.transfers} />}
          </div>
          <aside className="dk-col" aria-label={t('Лидеры и лазарет')}>
            {has('leaders') && team.leaders && <Leaders leaders={team.leaders} />}
            {has('injuries') && injuries.length > 0 && <Infirmary injuries={injuries} />}
          </aside>
        </div>
      </>
    );
  }

  return (
    <>
      {team.stale && (
        <p className="tm-stale" role="status">
          {t('Данные могли устареть · обновлено в {time} МСК', { time: formatTime(team.updated_at) })}
        </p>
      )}
      {has('leaders') && team.leaders && <Leaders leaders={team.leaders} />}
      {has('injuries') && injuries.length > 0 && <Infirmary injuries={injuries} />}
      {has('squad') && team.squad && <Squad team={team} outById={outById} />}
      {has('transfers') && team.transfers && <Transfers transfers={team.transfers} />}
    </>
  );
}

/* ---------- лидеры сезона ---------- */

function Leaders({ leaders }: { leaders: NonNullable<TeamResponse['leaders']> }) {
  const links = usePlayerLinks();
  const cards: { key: 'goals' | 'assists' | 'rating'; label: string }[] = [
    { key: 'goals', label: t('Голы') },
    { key: 'assists', label: isEn() ? 'Assists' : 'Передачи' }, // «Передачи» в словаре — пасы (матч)
    { key: 'rating', label: t('Оценка') },
  ];
  const items = cards
    .map((c) => ({ ...c, top: leaders[c.key]?.[0] as Leader | undefined }))
    .filter((c) => c.top);
  if (!items.length) return null;
  return (
    <section className="tm-leaders" aria-label={t('Лидеры сезона')}>
      {items.map(({ key, label, top }) => (
        <Card key={key} inset={false} as="div" className="tm-leader">
          <PlayerTap player={top!} {...links} className="tm-leader__tap" label={t('{label}: {name} — карточка игрока', { label, name: top!.name })}>
            <div className="tm-leader__head">
              <span className="tm-leader__label">{label}</span>
              <PlayerPhoto id={top!.id} name={top!.name} size={30} />
            </div>
            <div className={key === 'rating' ? 'tm-leader__val disp gold' : 'tm-leader__val disp'}>
              {key === 'rating' ? top!.value.toFixed(1) : top!.value}
            </div>
            <div className="tm-leader__name">{top!.name}</div>
          </PlayerTap>
        </Card>
      ))}
    </section>
  );
}

/* ---------- лазарет ---------- */

function Infirmary({ injuries }: { injuries: Injury[] }) {
  const links = usePlayerLinks();
  const rows = injuries.map((i) => ({ ...i, ret: returnInfo(i.expected_return) }));
  const out = rows
    .filter((r) => !r.ret.back)
    .sort((a, b) => (a.ret.date?.getTime() ?? 9e15) - (b.ret.date?.getTime() ?? 9e15));
  const back = rows.filter((r) => r.ret.back);
  return (
    <Card ariaLabel={t('Лазарет')}>
      <SectionHeader
        title={t('Лазарет')}
        aside={out.length ? `${out.length} ${plural(out.length, ['игрок', 'игрока', 'игроков'])}` : t('все здоровы')}
      />
      <ul className="tm-list">
        {out.map((r) => (
          <li key={r.id}>
            <PlayerTap player={r} {...links} className="tm-inj">
              <PlayerPhoto id={r.id} name={r.name} size={36} />
              <div className="tm-inj__main">
                <div className="tm-name">{r.name}</div>
                <div className="tm-sub">{r.type === 'suspension' ? t('дисквалификация') : t('травма')}</div>
              </div>
              <span className="tm-inj__ret">
                {r.ret.past ? (
                  <>
                    {t('ожидался:')}
                    <br />
                    {r.ret.text}
                  </>
                ) : (
                  r.ret.text
                )}
              </span>
            </PlayerTap>
          </li>
        ))}
      </ul>
      {back.length > 0 && (
        <>
          <div className="tm-group tm-group--back">{t('Вернулись в общую группу · {n}', { n: back.length })}</div>
          <ul className="tm-list">
            {back.map((r) => (
              <li key={r.id}>
                <PlayerTap player={r} {...links} className="tm-inj">
                  <PlayerPhoto id={r.id} name={r.name} size={36} />
                  <div className="tm-inj__main">
                    <div className="tm-name">{r.name}</div>
                  </div>
                </PlayerTap>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

/* ---------- состав ---------- */

function Squad({ team, outById }: { team: TeamResponse; outById: Map<number, Injury> }) {
  const links = usePlayerLinks();
  return (
    <Card ariaLabel={t('Состав')}>
      <SectionHeader title={t('Состав')} />
      {team.coach && <CoachRow coach={team.coach} />}
      {LINES.map(({ key, title }) => {
        const players = team.squad?.[key] ?? [];
        if (!players.length) return null;
        return (
          <section key={key} aria-label={title}>
            <h3 className="tm-group">
              {title} · {players.length}
            </h3>
            <ul className="tm-list">
              {players.map((p) => (
                <PlayerRow key={p.id} p={p} line={key} out={outById.get(p.id)} links={links} />
              ))}
            </ul>
          </section>
        );
      })}
    </Card>
  );
}

/** Главный тренер: фото (id FotMob — /img/player/{id}.png) и флаг; карточки тренера нет — без ссылки. */
function CoachRow({ coach }: { coach: NonNullable<TeamResponse['coach']> }) {
  const iso = flagIso(coach.country?.flag);
  return (
    <section aria-label={t('Тренер')}>
      <h3 className="tm-group">{t('Тренер')}</h3>
      <div className="tm-player tm-coach">
        <span className="tm-player__num" aria-hidden="true" />
        {coach.id != null && <PlayerPhoto id={coach.id} name={coach.name} size={40} />}
        <div className="tm-player__main">
          <div className="tm-name">{coach.name}</div>
          <div className="tm-sub">
            {iso && <Flag iso2={iso} name={coach.country?.name ?? ''} width={16} className="tm-flag" />}
            {t('главный тренер')}
          </div>
        </div>
      </div>
    </section>
  );
}

function PlayerRow({ p, line, out, links }: { p: SquadPlayer; line: LineKey; out?: Injury; links: PlayerLinkProps }) {
  const pos = positionRu(p.position, line);
  const age = ageText(p.age);
  const iso = flagIso(p.country?.flag);
  const suspended = out?.type === 'suspension' && !p.injured;
  return (
    <li>
      <PlayerTap player={p} {...links} className="tm-player">
        <span className="tm-player__num" aria-label={p.number != null ? t('номер {n}', { n: p.number }) : undefined}>
          {p.number ?? ''}
        </span>
        <PlayerPhoto id={p.id} name={p.name} size={40} />
        <div className="tm-player__main">
          <div className="tm-name">{p.name}</div>
          <div className="tm-sub">
            {iso && <Flag iso2={iso} name={p.country?.name ?? ''} width={16} className="tm-flag" />}
            {[pos, age].filter(Boolean).join(' · ')}
          </div>
        </div>
        {p.injured ? <Badge tone="injury" /> : suspended ? <Badge tone="injury">{t('дискв.')}</Badge> : null}
      </PlayerTap>
    </li>
  );
}

/* ---------- состав сеткой (сайт на компьютере) ---------- */

function SquadGrid({ team, outById }: { team: TeamResponse; outById: Map<number, Injury> }) {
  const links = usePlayerLinks();
  const coach = team.coach;
  const coachIso = flagIso(coach?.country?.flag);
  return (
    <section className="tm-grid" aria-label={t('Состав')}>
      {coach && (
        <div className="tm-gline">
          <h2 className="tm-gline__title">{t('Главный тренер')}</h2>
          <div className="tm-cards">
            <div className="tm-card tm-card--coach">
              <span className="tm-card__photo">{coach.id != null && <PlayerPhoto id={coach.id} name={coach.name} size={112} />}</span>
              <span className="tm-card__name">{coach.name}</span>
              <span className="tm-card__sub">
                {coachIso && <Flag iso2={coachIso} name={coach.country?.name ?? ''} width={16} className="tm-flag" />}
                {t('главный тренер')}
              </span>
            </div>
          </div>
        </div>
      )}
      {LINES.map(({ key, title }) => {
        const players = team.squad?.[key] ?? [];
        if (!players.length) return null;
        return (
          <div key={key} className="tm-gline">
            <h2 className="tm-gline__title">
              {title} <span className="tm-gline__n">{players.length}</span>
            </h2>
            <ul className="tm-cards">
              {players.map((p) => {
                const out = outById.get(p.id);
                const suspended = out?.type === 'suspension' && !p.injured;
                const iso = flagIso(p.country?.flag);
                const age = ageText(p.age);
                return (
                  <li key={p.id}>
                    <PlayerTap player={p} {...links} className="tm-card">
                      {p.number != null && (
                        <span className="tm-card__num" aria-label={t('номер {n}', { n: p.number })}>
                          {p.number}
                        </span>
                      )}
                      {(p.injured || suspended) && (
                        <span className="tm-card__badge">{p.injured ? <Badge tone="injury" /> : <Badge tone="injury">{t('дискв.')}</Badge>}</span>
                      )}
                      <span className="tm-card__photo">
                        <PlayerPhoto id={p.id} name={p.name} size={112} />
                      </span>
                      <span className="tm-card__name">{p.name}</span>
                      <span className="tm-card__sub">
                        {iso && <Flag iso2={iso} name={p.country?.name ?? ''} width={16} className="tm-flag" />}
                        {[positionRu(p.position, key), age].filter(Boolean).join(' · ')}
                      </span>
                    </PlayerTap>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

/* ---------- трансферы ---------- */

const SHOW_TRANSFERS = 5;

function Transfers({ transfers }: { transfers: NonNullable<TeamResponse['transfers']> }) {
  const groups = [
    { key: 'in' as const, title: t('Пришли'), list: transfers.in ?? [] },
    { key: 'out' as const, title: t('Ушли'), list: transfers.out ?? [] },
  ].filter((g) => g.list.length);
  if (!groups.length) return null;
  return (
    <Card ariaLabel={t('Трансферы')}>
      <SectionHeader title={t('Трансферы')} />
      {groups.map((g) => (
        <TransferGroup key={g.key} title={g.title} dir={g.key} list={g.list} />
      ))}
    </Card>
  );
}

function TransferGroup({ title, dir, list }: { title: string; dir: 'in' | 'out'; list: Transfer[] }) {
  const [all, setAll] = useState(false);
  const links = usePlayerLinks();
  const shown = all ? list : list.slice(0, SHOW_TRANSFERS);
  return (
    <section aria-label={title}>
      <h3 className="tm-group">
        {title} · {list.length}
      </h3>
      <ul className="tm-list">
        {shown.map((tr, i) => {
          const club = dir === 'in' ? tr.from : tr.to;
          const fee = feeText(tr);
          return (
            <li key={`${tr.player.id}-${i}`}>
              <PlayerTap player={tr.player} {...links} className="tm-tr">
                <PlayerPhoto id={tr.player.id} name={tr.player.name} size={36} />
                <div className="tm-tr__main">
                  <div className="tm-name">{tr.player.name}</div>
                  <div className="tm-sub">
                    {club.id != null && club.logo ? <TeamCrest id={club.id} name="" size={20} className="tm-tr__crest" /> : null}
                    <span className="tm-tr__club">
                      {/free agent/i.test(club.name) ? t('свободный агент') : dir === 'in' ? t('из {club}', { club: club.name }) : t('в {club}', { club: club.name })}
                    </span>
                  </div>
                </div>
                <span className={tr.loan || fee === t('аренда') ? 'tm-tr__fee tm-tr__fee--loan' : 'tm-tr__fee'}>{fee ?? '—'}</span>
              </PlayerTap>
            </li>
          );
        })}
      </ul>
      {list.length > SHOW_TRANSFERS && (
        <button type="button" className="tm-more" onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? tc('list', 'Свернуть') : t('Ещё {n}', { n: list.length - SHOW_TRANSFERS })}
        </button>
      )}
    </section>
  );
}
