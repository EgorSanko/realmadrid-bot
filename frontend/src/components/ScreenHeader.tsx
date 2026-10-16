/** Шапка раздела, как .topbar в макете. На главной — логотип-надпись. */
export function ScreenHeader({
  title,
  brand = false,
  live = false,
}: {
  title: string;
  brand?: boolean;
  /** идёт эфир — бейдж «В ЭФИРЕ», как в a-live.html */
  live?: boolean;
}) {
  if (brand) {
    return (
      <header className="brandbar">
        <h1 className="brand" aria-label={`Мадридиста — ${title}`}>
          <span className="brand__mark" aria-hidden="true" />
          МАДРИДИСТА
        </h1>
        {live && (
          <span className="badge-live">
            <span className="live-dot" />В ЭФИРЕ
          </span>
        )}
      </header>
    );
  }
  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
    </header>
  );
}
