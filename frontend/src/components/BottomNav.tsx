import { NavLink, useLocation } from 'react-router';
import { Icon, SECTIONS, sectionActive } from '../sections';

export function BottomNav() {
  const { pathname } = useLocation();
  return (
    <nav className="bottom-nav" aria-label="Разделы">
      <div className="bottom-nav__inner">
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
