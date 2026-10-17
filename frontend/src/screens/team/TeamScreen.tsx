import { useEffect, useMemo, useState } from 'react';
import { usePlayerLinks } from '../../lib/playerNav';
import { Badge, Card, ErrorState, Flag, PlayerPhoto, PlayerTap, SectionHeader, Skeleton, TeamCrest, type PlayerLinkProps } from '../../ui';
import { formatTime } from '../../ui/format';
import { errorText, useApiResource } from '../../lib/apiResource';
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
    document.title = 'Состав «Реала», лазарет и трансферы — Мадридиста';
  }, []);
  const { data, error, loading, reload } = useApiResource<TeamResponse>('/api/team');

  return (
    <main className="tm">
      <header className="topbar">
        <h1 className="topbar__title">Команда</h1>
        <span className="tm-season">сезон {seasonLabel()}</span>
      </header>
      {data ? (
        <TeamBody t={data} />
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

function TeamBody({ t }: { t: TeamResponse }) {
  const has = (k: string) => t.available.includes(k);
  const injuries = t.injuries ?? [];
  // дисквалификации и травмы из лазарета — для бейджа в составе (кроме тех, кто уже тренируется)
  const outById = useMemo(() => {
    const m = new Map<number, Injury>();
    for (const i of injuries) {
      const r = returnInfo(i.expected_return);
      if (!r.back && !r.past) m.set(i.id, i);
    }
    return m;
  }, [injuries]);

  return (
    <>
      {t.stale && (
        <p className="tm-stale" role="status">
          Данные могли устареть · обновлено в {formatTime(t.updated_at)} МСК
        </p>
      )}
      {has('leaders') && t.leaders && <Leaders leaders={t.leaders} />}
      {has('injuries') && injuries.length > 0 && <Infirmary injuries={injuries} />}
      {has('squad') && t.squad && <Squad t={t} outById={outById} />}
      {has('transfers') && t.transfers && <Transfers transfers={t.transfers} />}
    </>
  );
}

/* ---------- лидеры сезона ---------- */

function Leaders({ leaders }: { leaders: NonNullable<TeamResponse['leaders']> }) {
  const links = usePlayerLinks();
  const cards: { key: 'goals' | 'assists' | 'rating'; label: string }[] = [
    { key: 'goals', label: 'Голы' },
    { key: 'assists', label: 'Передачи' },
    { key: 'rating', label: 'Оценка' },
  ];
  const items = cards
    .map((c) => ({ ...c, top: leaders[c.key]?.[0] as Leader | undefined }))
    .filter((c) => c.top);
  if (!items.length) return null;
  return (
    <section className="tm-leaders" aria-label="Лидеры сезона">
      {items.map(({ key, label, top }) => (
        <Card key={key} inset={false} as="div" className="tm-leader">
          <PlayerTap player={top!} {...links} className="tm-leader__tap" label={`${label}: ${top!.name} — карточка игрока`}>
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
    <Card ariaLabel="Лазарет">
      <SectionHeader
        title="Лазарет"
        aside={out.length ? `${out.length} ${plural(out.length, ['игрок', 'игрока', 'игроков'])}` : 'все здоровы'}
      />
      <ul className="tm-list">
        {out.map((r) => (
          <li key={r.id}>
            <PlayerTap player={r} {...links} className="tm-inj">
              <PlayerPhoto id={r.id} name={r.name} size={36} />
              <div className="tm-inj__main">
                <div className="tm-name">{r.name}</div>
                <div className="tm-sub">{r.type === 'suspension' ? 'дисквалификация' : 'травма'}</div>
              </div>
              <span className="tm-inj__ret">
                {r.ret.past ? (
                  <>
                    ожидался:
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
          <div className="tm-group tm-group--back">Вернулись в общую группу · {back.length}</div>
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

function Squad({ t, outById }: { t: TeamResponse; outById: Map<number, Injury> }) {
  const links = usePlayerLinks();
  return (
    <Card ariaLabel="Состав">
      <SectionHeader title="Состав" />
      {t.coach && <CoachRow coach={t.coach} />}
      {LINES.map(({ key, title }) => {
        const players = t.squad?.[key] ?? [];
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
    <section aria-label="Тренер">
      <h3 className="tm-group">Тренер</h3>
      <div className="tm-player tm-coach">
        <span className="tm-player__num" aria-hidden="true" />
        {coach.id != null && <PlayerPhoto id={coach.id} name={coach.name} size={40} />}
        <div className="tm-player__main">
          <div className="tm-name">{coach.name}</div>
          <div className="tm-sub">
            {iso && <Flag iso2={iso} name={coach.country?.name ?? ''} width={16} className="tm-flag" />}
            главный тренер
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
        <span className="tm-player__num" aria-label={p.number != null ? `номер ${p.number}` : undefined}>
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
        {p.injured ? <Badge tone="injury" /> : suspended ? <Badge tone="injury">дискв.</Badge> : null}
      </PlayerTap>
    </li>
  );
}

/* ---------- трансферы ---------- */

const SHOW_TRANSFERS = 5;

function Transfers({ transfers }: { transfers: NonNullable<TeamResponse['transfers']> }) {
  const groups = [
    { key: 'in' as const, title: 'Пришли', list: transfers.in ?? [] },
    { key: 'out' as const, title: 'Ушли', list: transfers.out ?? [] },
  ].filter((g) => g.list.length);
  if (!groups.length) return null;
  return (
    <Card ariaLabel="Трансферы">
      <SectionHeader title="Трансферы" />
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
                      {/free agent/i.test(club.name) ? 'свободный агент' : `${dir === 'in' ? 'из' : 'в'} ${club.name}`}
                    </span>
                  </div>
                </div>
                <span className={fee === 'аренда' ? 'tm-tr__fee tm-tr__fee--loan' : 'tm-tr__fee'}>{fee ?? '—'}</span>
              </PlayerTap>
            </li>
          );
        })}
      </ul>
      {list.length > SHOW_TRANSFERS && (
        <button type="button" className="tm-more" onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? 'Свернуть' : `Ещё ${list.length - SHOW_TRANSFERS}`}
        </button>
      )}
    </section>
  );
}
