import { useEffect } from 'react';
import { useNavigate } from 'react-router';
import { retrieveLaunchParams } from '@tma.js/sdk-react';
import { AuthFetchError, authFetch, bootstrapAuth, inMiniApp } from '../lib/auth';
import { joinedMessage, parseStartParam } from '../lib/startParam';
import { t } from '../lib/i18n';

function launchStartParam(): string | null {
  try {
    return retrieveLaunchParams().tgWebAppStartParam ?? null;
  } catch {
    return null;
  }
}

/**
 * Разбор `startapp` мини-аппа один раз за запуск: profile → /profile, match_<id> → /match/<id>,
 * quiz / penalty → /games/…,
 * league_<код> → вступить в лигу и открыть профиль с сообщением. Берём start_param из подписанного
 * initData (ответ входа), иначе — из параметров запуска.
 */
export function StartParamHandler() {
  const navigate = useNavigate();
  useEffect(() => {
    if (!inMiniApp()) return;
    let alive = true;
    void (async () => {
      const st = await bootstrapAuth();
      const raw = st.startParam ?? launchStartParam();
      const act = parseStartParam(raw);
      if (!act || !alive) return;
      // перезагрузка мини-аппа сохраняет параметры запуска — не вступаем и не переходим повторно
      const key = `rm-start:${raw}`;
      try {
        if (sessionStorage.getItem(key)) return;
        sessionStorage.setItem(key, '1');
      } catch {
        /* приватный режим — обработаем ещё раз, вступление идемпотентно */
      }
      if (act.kind === 'profile') navigate('/profile');
      else if (act.kind === 'match') navigate(`/match/${act.id}`);
      else if (act.kind === 'game') navigate(`/games/${act.game}`);
      else {
        let flash: string;
        try {
          const r = await authFetch<{ name: string; joined: boolean }>('/api/predict/leagues/join', {
            method: 'POST',
            body: { code: act.code },
          });
          flash = joinedMessage(r.name, r.joined);
        } catch (e) {
          flash = e instanceof AuthFetchError ? e.message : t('Не удалось вступить в лигу');
        }
        navigate('/profile', { state: { flash } });
      }
    })();
    return () => {
      alive = false;
    };
  }, [navigate]);
  return null;
}
