import type { ReactNode } from 'react';
import { Icon } from '../sections';

export function EmptyState({ stage, text, icon }: { stage: number; text: string; icon: ReactNode }) {
  return (
    <section className="empty" aria-live="polite">
      <div className="empty__icon">
        <Icon>{icon}</Icon>
      </div>
      <span className="empty__chip">Этап {stage}</span>
      <p className="empty__title">Раздел появится на этапе {stage}</p>
      <p className="empty__text">{text}</p>
    </section>
  );
}
