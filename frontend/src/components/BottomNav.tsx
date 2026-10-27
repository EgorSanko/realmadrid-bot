import type { CSSProperties } from 'react';
import { NavLink, useLocation } from 'react-router';
import { t } from '../lib/i18n';
import { Icon, SECTIONS, sectionActive } from '../sections';

export function BottomNav() {
  const { pathname } = useLocation();
  const active = SECTIONS.findIndex((s) => (s.path === '/' ? pathname === '/' : sectionActive(s, pathname)));
  return (
    <nav className="bottom-nav" aria-label={t('Разделы')}>
      <div className="bottom-nav__inner">
        {/* золотая метка активной вкладки: одна на всё меню, переезжает к выбранной (transform) */}
        <span
          className="bottom-nav__ind"
          aria-hidden="true"
          style={{ '--i': Math.max(active, 0), opacity: active < 0 ? 0 : 1 } as CSSProperties}
        />
        {SECTIONS.map((s) => (
          <NavLink
            key={s.path}
            to={s.path}
            end={s.path === '/'}
            className={({ isActive }) => (isActive || sectionActive(s, pathname) ? 'on' : undefined)}
          >
            <Icon>{s.icon}</Icon>
            {s.label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
