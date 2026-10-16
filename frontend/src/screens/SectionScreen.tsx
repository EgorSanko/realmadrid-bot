import { useEffect } from 'react';
import { ScreenHeader } from '../components/ScreenHeader';
import { EmptyState } from '../components/EmptyState';
import { StreamBlock } from '../components/StreamBlock';
import { useStream } from '../lib/stream';
import type { Section } from '../sections';

/** Этап 0: у каждого раздела — шапка и пустое состояние. На главной сверху — блок эфира (этап 3). */
export function SectionScreen({ section }: { section: Section }) {
  const isHome = section.path === '/';

  useEffect(() => {
    document.title = isHome ? 'Мадридиста' : `${section.label} — Мадридиста`;
  }, [isHome, section.label]);

  if (isHome) return <HomeScreen section={section} />;

  return (
    <main>
      <ScreenHeader title={section.label} />
      <EmptyState stage={section.stage} text={section.about} icon={section.icon} />
    </main>
  );
}

function HomeScreen({ section }: { section: Section }) {
  const stream = useStream();
  return (
    <main>
      <ScreenHeader title={section.label} brand live={!!stream?.live} />
      <StreamBlock stream={stream} />
      <EmptyState stage={section.stage} text={section.about} icon={section.icon} />
    </main>
  );
}
