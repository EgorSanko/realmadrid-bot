// src/pages/Stream.jsx — список активных стримов RM-матча.
//
// Без auth. Данные из /api/streams ({name, url, type, http_url?}).
// Для iframe-стримов просто рендерим <iframe>. HLS вынесен в Stream.legacy
// и пока не подключён — добавим в отдельном раунде с lazy-load hls.js.

import React, { useEffect, useState } from 'react';
import { api } from '@/lib/api.js';

export default function Stream() {
  const [streams, setStreams] = useState(null);
  const [active, setActive] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.streams.list()
      .then((list) => { setStreams(list); if (list[0]) setActive(list[0]); })
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="p-4 max-w-3xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Прямая трансляция</h2>

      {error && <div className="text-red-400 mb-4">Ошибка: {error}</div>}
      {streams == null && !error && <div className="text-zinc-500">Загрузка...</div>}
      {streams?.length === 0 && (
        <div className="bg-zinc-800 rounded p-6 text-center text-zinc-400">
          Сейчас нет активных трансляций. Откройте страницу во время матча.
        </div>
      )}

      {streams?.length > 0 && (
        <>
          <div className="flex gap-2 mb-4 flex-wrap">
            {streams.map((s, i) => (
              <button key={i} onClick={() => setActive(s)}
                className={`px-3 py-1.5 rounded text-sm ${
                  active === s ? 'bg-rm-gold text-zinc-900 font-semibold' : 'bg-zinc-800 text-zinc-300'
                }`}>
                {s.name || `Поток ${i + 1}`}
              </button>
            ))}
          </div>

          {active && (
            <div className="bg-black rounded overflow-hidden" style={{ aspectRatio: '16 / 9' }}>
              {active.type === 'iframe' && (
                <iframe
                  src={active.url}
                  className="w-full h-full"
                  allow="autoplay; fullscreen; encrypted-media"
                  allowFullScreen
                  title={active.name || 'stream'}
                />
              )}
              {active.type === 'acestream' && active.http_url && (
                <iframe
                  src={active.http_url}
                  className="w-full h-full"
                  allow="autoplay; fullscreen"
                  allowFullScreen
                  title={active.name || 'acestream'}
                />
              )}
              {active.type === 'hls' && (
                <div className="flex items-center justify-center h-full text-zinc-500">
                  HLS-плеер будет добавлен в следующем раунде Block 3.
                  <br />
                  Прямая ссылка: <a href={active.url} className="text-rm-gold ml-1">{active.url}</a>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
