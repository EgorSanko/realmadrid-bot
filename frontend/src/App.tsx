import { Suspense, lazy, useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router';
import { BottomNav } from './components/BottomNav';
import { SiteFooter } from './components/SiteFooter';
import { SiteHeader } from './components/SiteHeader';
import { RouteMeta } from './components/RouteMeta';
import { StartParamHandler } from './components/StartParamHandler';
import { backgroundOf } from './lib/playerNav';
import { useDesktop } from './lib/shell';
import { SectionScreen } from './screens/SectionScreen';
import { SECTIONS } from './sections';
import HomeScreen from './screens/HomeScreen';
import MatchesScreen from './screens/MatchesScreen';

// скрытый маршрут, отдельный чанк — зрителям не грузится
const AdminScreen = lazy(() => import('./screens/AdminScreen'));
// витрина компонентов /dev/ui — только в dev-сервере или при сборке с VITE_UIKIT=1:
// в обычной прод-сборке условие — константа false, маршрута и чанка UiKitPage в dist нет
const UiKitPage =
  import.meta.env.DEV || import.meta.env.VITE_UIKIT === '1' ? lazy(() => import('./dev/UiKitPage')) : null;
// экран матча, «Команда», «Медиа» и карточка игрока — свои ленивые чанки
const MatchScreen = lazy(() => import('./screens/match/MatchScreen'));
const TeamScreen = lazy(() => import('./screens/team/TeamScreen'));
const MediaScreen = lazy(() => import('./screens/media/MediaScreen'));
const PlayerScreen = lazy(() => import('./screens/player/PlayerScreen'));
// чтение новости и просмотр видео внутри приложения — свои ленивые чанки (iframe YouTube — только там)
const NewsScreen = lazy(() => import('./screens/media/NewsScreen'));
const VideoScreen = lazy(() => import('./screens/media/VideoScreen'));
// профиль и вход — свой ленивый чанк
const ProfileScreen = lazy(() => import('./screens/profile/ProfileScreen'));
// прогнозы — свой ленивый чанк (общая часть с блоком на главной — отдельный чанк)
const PredictScreen = lazy(() => import('./screens/predict/PredictScreen'));
// игры раздела «Игры» — викторина и пенальти, каждая своим ленивым чанком
const QuizScreen = lazy(() => import('./screens/games/QuizScreen'));
const PenaltyScreen = lazy(() => import('./screens/games/PenaltyScreen'));

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
  return (
    <>
      <ScrollToTop pathname={shown.pathname} />
      <StartParamHandler />
      <RouteMeta />
      {desktop && <SiteHeader />}
      <div className="app">
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
          {/* оставшиеся разделы-заглушки (сейчас — нет) */}
          {SECTIONS.filter((s) => !['/', '/matches', '/team', '/media', '/predict'].includes(s.path)).map((s) => (
            <Route key={s.path} path={s.path} element={<SectionScreen section={s} />} />
          ))}
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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
      {desktop ? <SiteFooter /> : <BottomNav />}
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
