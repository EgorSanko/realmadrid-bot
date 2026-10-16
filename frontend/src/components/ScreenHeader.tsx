/** Шапка раздела, как .topbar в макете. На главной — логотип-надпись. */
export function ScreenHeader({ title, brand = false }: { title: string; brand?: boolean }) {
  if (brand) {
    return (
      <header className="brandbar">
        <h1 className="brand" aria-label={`Мадридиста — ${title}`}>
          <span className="brand__mark" aria-hidden="true" />
          МАДРИДИСТА
        </h1>
      </header>
    );
  }
  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
    </header>
  );
}
