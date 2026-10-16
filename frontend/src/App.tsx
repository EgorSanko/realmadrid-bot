import { Suspense, lazy, useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router';
import { BottomNav } from './components/BottomNav';
import { SectionScreen } from './screens/SectionScreen';
import { SECTIONS } from './sections';

// скрытый маршрут, отдельный чанк — зрителям не грузится
const AdminScreen = lazy(() => import('./screens/AdminScreen'));
const UiKitPage = lazy(() => import('./dev/UiKitPage'));
// этапы 8 и 9 — свои ленивые чанки
const TeamScreen = lazy(() => import('./screens/team/TeamScreen'));
const MediaScreen = lazy(() => import('./screens/media/MediaScreen'));

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

export function App() {
  return (
    <BrowserRouter>
      <ScrollToTop />
      <div className="app">
        <Routes>
          {/* раньше заглушек из SECTIONS: при одинаковом пути побеждает первый маршрут */}
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
          {SECTIONS.map((s) => (
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
          {/* скрытая витрина компонентов, не в меню; отдельный ленивый чанк */}
          <Route
            path="/dev/ui"
            element={
              <Suspense fallback={null}>
                <UiKitPage />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
      <BottomNav />
    </BrowserRouter>
  );
}
