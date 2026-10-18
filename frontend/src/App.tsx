import { Suspense, lazy, useEffect, useLayoutEffect, useRef, type ComponentType } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router';
import { BottomNav } from './components/BottomNav';
import { GoalLayer } from './components/GoalLayer';
import { PullToRefresh } from './components/PullToRefresh';
import { SiteFooter } from './components/SiteFooter';
import { SiteHeader } from './components/SiteHeader';
import { RouteMeta } from './components/RouteMeta';
import { StartParamHandler } from './components/StartParamHandler';
import { Toaster } from './components/Toaster';
import { backgroundOf } from './lib/playerNav';
import { useDesktop } from './lib/shell';
import { rememberRects } from './lib/flipOrigin';
import { reducedMotion } from './lib/motion';
import { SECTIONS, sectionActive } from './sections';
import HomeScreen from './screens/HomeScreen';
import MatchesScreen from './screens/MatchesScreen';

// чанки экранов: те, что открываются из меню и с главной, подгружаются в фоне после первой отрисовки —
// иначе при первом нажатии вкладки экран ~0,3–1 с пустой (Suspense fallback), страница короче окна, и меню прыгает
const chunks = {
  match: () => import('./screens/match/MatchScreen'),
  team: () => import('./screens/team/TeamScreen'),
  media: () => import('./screens/media/MediaScreen'),
  player: () => import('./screens/player/PlayerScreen'),
  predict: () => import('./screens/predict/PredictScreen'),
  quiz: () => import('./screens/games/QuizScreen'),
  penalty: () => import('./screens/games/PenaltyScreen'),
};

/**
 * lazy() с подгрузкой заранее: пока чанк не загружен — обычный lazy (Suspense), после загрузки
 * экран рисуется сразу. Простой lazy даже по готовому чанку показывает пустой fallback минимум ~300 мс.
 */
function preloadable<P extends object>(load: () => Promise<{ default: ComponentType<P> }>) {
  let Ready: ComponentType<P> | null = null;
  const get = () =>
    load().then((m) => {
      Ready = m.default;
      return m;
    });
  const Lazy = lazy(get);
  function Screen(props: P) {
    return Ready ? <Ready {...props} /> : <Lazy {...props} />;
  }
  return Object.assign(Screen, { preload: get });
}

function usePreloadScreens() {
  useEffect(() => {
    const idle = (window as { requestIdleCallback?: (f: () => void, o?: { timeout: number }) => number }).requestIdleCallback;
    const run = () => {
      // по одному, чтобы не отнимать сеть у данных текущего экрана
      SCREENS.reduce<Promise<unknown>>((q, s) => q.then(s.preload).catch(() => {}), Promise.resolve());
    };
    const t = window.setTimeout(() => (idle ? idle(run, { timeout: 2000 }) : run()), 1200);
    return () => window.clearTimeout(t);
  }, []);
}

// скрытый маршрут, отдельный чанк — зрителям не грузится
const AdminScreen = lazy(() => import('./screens/AdminScreen'));
// витрина компонентов /dev/ui — только в dev-сервере или при сборке с VITE_UIKIT=1:
// в обычной прод-сборке условие — константа false, маршрута и чанка UiKitPage в dist нет
const UiKitPage =
  import.meta.env.DEV || import.meta.env.VITE_UIKIT === '1' ? lazy(() => import('./dev/UiKitPage')) : null;
// экран матча, «Команда», «Медиа» и карточка игрока — свои ленивые чанки
const MatchScreen = preloadable(chunks.match);
const TeamScreen = preloadable(chunks.team);
const MediaScreen = preloadable(chunks.media);
const PlayerScreen = preloadable(chunks.player);
// чтение новости и просмотр видео внутри приложения — свои ленивые чанки (iframe YouTube — только там)
const NewsScreen = lazy(() => import('./screens/media/NewsScreen'));
const VideoScreen = lazy(() => import('./screens/media/VideoScreen'));
// профиль и вход — свой ленивый чанк
const ProfileScreen = lazy(() => import('./screens/profile/ProfileScreen'));
// прогнозы — свой ленивый чанк (общая часть с блоком на главной — отдельный чанк)
const PredictScreen = preloadable(chunks.predict);
// игры раздела «Игры» — викторина и пенальти, каждая своим ленивым чанком
const QuizScreen = preloadable(chunks.quiz);
const PenaltyScreen = preloadable(chunks.penalty);
// порядок фоновой подгрузки: сначала вкладки меню, потом матч и игрок
const SCREENS = [TeamScreen, MediaScreen, PredictScreen, QuizScreen, MatchScreen, PlayerScreen, PenaltyScreen];
// политика конфиденциальности и условия — свой ленивый чанк
const LegalScreen = lazy(() => import('./screens/legal/LegalScreen'));
// неизвестный адрес — страница «не найдено» (раньше молча уводили на главную)
const NotFoundScreen = lazy(() => import('./screens/NotFoundScreen'));

/** Индекс раздела нижнего меню для адреса (−1 — не раздел: матч, игрок, новость…). */
function sectionIndex(pathname: string): number {
  return SECTIONS.findIndex((s) => (s.path === '/' ? pathname === '/' : sectionActive(s, pathname)));
}

/**
 * Моушен переходов:
 *  — между разделами меню содержимое въезжает сдвигом со стороны выбранной вкладки и проявляется;
 *  — нажатие на матч (любая ссылка /match/…) запоминает, где стояли эмблемы команд: экран матча
 *    проиграет их полёт в свою шапку (lib/flipOrigin.ts).
 * Навигацию, «назад», прокрутку и прямые ссылки не трогает — только transform/opacity контейнера.
 */
function useRouteMotion(pathname: string, app: React.RefObject<HTMLDivElement | null>) {
  const prev = useRef(sectionIndex(pathname));
  useLayoutEffect(() => {
    const i = sectionIndex(pathname);
    const was = prev.current;
    prev.current = i;
    const el = app.current;
    if (!el || i < 0 || was < 0 || i === was || typeof el.animate !== 'function') return;
    const rm = reducedMotion();
    const play = () => el.animate(
      rm
        ? [{ opacity: 0.4 }, { opacity: 1 }]
        : [
            { opacity: 0, transform: `translateX(${i > was ? 22 : -22}px)` },
            { opacity: 1, transform: 'none' },
          ],
      { duration: rm ? 160 : 300, easing: 'cubic-bezier(.22,1,.36,1)' },
    );
    // экран ещё грузится (пустой Suspense) — сдвиг играем, когда появится содержимое, а не на пустоте
    if (el.childElementCount) return void play();
    const mo = new MutationObserver(() => {
      if (!el.childElementCount) return;
      mo.disconnect();
      play();
    });
    mo.observe(el, { childList: true });
    const t = window.setTimeout(() => mo.disconnect(), 3000);
    return () => {
      mo.disconnect();
      window.clearTimeout(t);
    };
  }, [pathname, app]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const a = (e.target as Element | null)?.closest?.('a[href^="/match/"]');
      if (!a) return;
      const id = a.getAttribute('href')!.split('/')[2];
      const crests = Array.from(a.querySelectorAll('img.ui-crest'));
      if (crests.length >= 2) rememberRects(`match:${id}`, crests.slice(0, 2).map((c) => c.getBoundingClientRect()));
    };
    document.addEventListener('click', onClick, true);
    return () => document.removeEventListener('click', onClick, true);
  }, []);
}

function ScrollToTop({ pathname }: { pathname: string }) {
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

const player = (
  <Suspense fallback={null}>
    <PlayerScreen />
  </Suspense>
);

const newsReader = (
  <Suspense fallback={null}>
    <NewsScreen />
  </Suspense>
);

const videoPlayer = (
  <Suspense fallback={null}>
    <VideoScreen />
  </Suspense>
);

function AppRoutes() {
  const location = useLocation();
  const desktop = useDesktop();
  // карточка игрока, открытая из приложения, лежит поверх экрана, с которого её открыли:
  // он остаётся смонтированным (прокрутка, вкладка, опрос), «назад» возвращает ровно туда.
  // Прямой заход по ссылке — фона нет, карточка рисуется одна.
  // Сайт на компьютере: игрок, новость и видео — обычные страницы между шапкой и подвалом, без слоя.
  const bg = desktop ? undefined : backgroundOf(location);
  const shown = bg ?? location;
  const app = useRef<HTMLDivElement>(null);
  useRouteMotion(shown.pathname, app);
  usePreloadScreens();
  return (
    <>
      <ScrollToTop pathname={shown.pathname} />
      <StartParamHandler />
      <RouteMeta />
      {desktop && <SiteHeader />}
      <div className="app" ref={app}>
        <Routes location={shown}>
          <Route path="/" element={<HomeScreen />} />
          <Route path="/matches" element={<MatchesScreen />} />
          <Route
            path="/team"
            element={
              <Suspense fallback={null}>
                <TeamScreen />
              </Suspense>
            }
          />
          <Route
            path="/media"
            element={
              <Suspense fallback={null}>
                <MediaScreen />
              </Suspense>
            }
          />
          <Route
            path="/predict"
            element={
              <Suspense fallback={null}>
                <PredictScreen />
              </Suspense>
            }
          />
          <Route path="/games" element={<Navigate to="/games/quiz" replace />} />
          <Route
            path="/games/quiz"
            element={
              <Suspense fallback={null}>
                <QuizScreen />
              </Suspense>
            }
          />
          <Route
            path="/games/penalty"
            element={
              <Suspense fallback={null}>
                <PenaltyScreen />
              </Suspense>
            }
          />
          <Route
            path="/admin"
            element={
              <Suspense fallback={null}>
                <AdminScreen />
              </Suspense>
            }
          />
          <Route
            path="/match/:id/*"
            element={
              <Suspense fallback={null}>
                <MatchScreen />
              </Suspense>
            }
          />
          <Route
            path="/profile"
            element={
              <Suspense fallback={null}>
                <ProfileScreen />
              </Suspense>
            }
          />
          <Route path="/player/:id" element={player} />
          <Route path="/news/:id" element={newsReader} />
          <Route path="/video/:id" element={videoPlayer} />
          <Route
            path="/privacy"
            element={
              <Suspense fallback={null}>
                <LegalScreen doc="privacy" />
              </Suspense>
            }
          />
          <Route
            path="/terms"
            element={
              <Suspense fallback={null}>
                <LegalScreen doc="terms" />
              </Suspense>
            }
          />
          {/* скрытая витрина компонентов, не в меню; отдельный ленивый чанк, в прод-сборку не входит */}
          {UiKitPage && (
            <Route
              path="/dev/ui"
              element={
                <Suspense fallback={null}>
                  <UiKitPage />
                </Suspense>
              }
            />
          )}
          <Route
            path="*"
            element={
              <Suspense fallback={null}>
                <NotFoundScreen />
              </Suspense>
            }
          />
        </Routes>
      </div>
      {desktop ? <SiteFooter /> : <BottomNav />}
      <Toaster />
      <GoalLayer />
      {!desktop && <PullToRefresh />}
      {bg && (
        <Routes>
          <Route path="/player/:id" element={player} />
          <Route path="/news/:id" element={newsReader} />
          <Route path="/video/:id" element={videoPlayer} />
          <Route path="*" element={null} />
        </Routes>
      )}
    </>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
