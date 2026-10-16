import { NavLink } from 'react-router';
import { Icon, SECTIONS } from '../sections';

export function BottomNav() {
  return (
    <nav className="bottom-nav" aria-label="Разделы">
      <div className="bottom-nav__inner">
        {SECTIONS.map((s) => (
          <NavLink
            key={s.path}
            to={s.path}
            end={s.path === '/'}
            className={({ isActive }) => (isActive ? 'on' : undefined)}
          >
            <Icon>{s.icon}</Icon>
            {s.label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
