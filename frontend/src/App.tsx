import { Suspense, lazy, useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router';
import { BottomNav } from './components/BottomNav';
import { SectionScreen } from './screens/SectionScreen';
import { SECTIONS } from './sections';

// скрытый маршрут, отдельный чанк — зрителям не грузится
const AdminScreen = lazy(() => import('./screens/AdminScreen'));
const UiKitPage = lazy(() => import('./dev/UiKitPage'));
// экран матча — отдельный ленивый чанк
const MatchScreen = lazy(() => import('./screens/match/MatchScreen'));

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
          <Route
            path="/match/:id/*"
            element={
              <Suspense fallback={null}>
                <MatchScreen />
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
