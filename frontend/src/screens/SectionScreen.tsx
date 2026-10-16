import { useEffect } from 'react';
import { ScreenHeader } from '../components/ScreenHeader';
import { EmptyState } from '../components/EmptyState';
import type { Section } from '../sections';

/** Этап 0: у каждого раздела — шапка и пустое состояние. */
export function SectionScreen({ section }: { section: Section }) {
  const isHome = section.path === '/';

  useEffect(() => {
    document.title = isHome ? 'Мадридиста' : `${section.label} — Мадридиста`;
  }, [isHome, section.label]);

  return (
    <main>
      <ScreenHeader title={section.label} brand={isHome} />
      <EmptyState stage={section.stage} text={section.about} icon={section.icon} />
    </main>
  );
}
