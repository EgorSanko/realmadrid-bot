/* match-videos-overlay.js — overlay-плеер для RM проекта (v26).
 *
 * Что делает:
 * - Подгружает /api/matches/results, строит map по дате → videos[]
 * - SITE список «Результаты»: добавляет chip-кнопки в карточку
 * - SITE/WEBAPP детальная страница матча: перехватывает «Обзор матча» / «Смотреть хайлайты»
 *   и добавляет рядом 1Т / 2Т / Полный (только на сайте)
 * - RuTube-видео (обзоры football-video.org): открывает rutube.ru/video/{id}/ в новой
 *   вкладке. Большинство этих видео блокируют embed на сторонних сайтах.
 * - Остальные провайдеры (hgcloud, VK Sport, cybervynx): модал с iframe-плеером.
 *
 * Live-трансляции:
 *   Админ /setstream URL → streams.json → /api/streams. Site рендерит нативно
 *   в /live tab. WebApp нативно не рендерит → overlay инжектит карточку
 *   «Прямая трансляция» поверх (только на webapp).
 */
(function () {
  if (window.__rmVideosOverlayLoaded) return;
  window.__rmVideosOverlayLoaded = true;

  var videosByDate = {};

  function normDate(s) {
    if (!s) return '';
    var m1 = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m1) return m1[1] + '-' + m1[2] + '-' + m1[3];
    var m2 = s.match(/(\d{2})\.(\d{2})\.(\d{4})/);
    if (m2) return m2[3] + '-' + m2[2] + '-' + m2[1];
    return s;
  }

  function labelFor(t) {
    return ({
      half1: '▶ 1 тайм',
      half2: '▶ 2 тайм',
      full: '▶ Полный матч',
      extratime: '▶ Доп. время',
      penalties: '▶ Серия пенальти',
      highlights: '▶ Обзор',
      goals: '▶ Голы',
      pregame: '▶ Превью'
    })[t] || ('▶ ' + t);
  }

  function unwrapVideoUrl(url) {
    if (!url) return url;
    return url.replace('https://hgcloud.to/', 'https://audinifer.com/')
              .replace('https://hglink.to/', 'https://audinifer.com/');
  }

  function loadVideos() {
    return fetch('/api/matches/results', { credentials: 'omit' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var m = {};
        var arr = (d && d.results) || [];
        for (var i = 0; i < arr.length; i++) {
          var x = arr[i];
          if (!x.videos || !x.videos.length) continue;
          m[normDate(x.date)] = x.videos;
        }
        videosByDate = m;
      })
      .catch(function () {});
  }

  function openModal(videoUrl, title, provider) {
    // RuTube блокирует embed для большинства футбольных обзоров → открываем
    // напрямую на их сайте в новой вкладке. Это решение пользователя — лучше
    // открыть rutube.ru, чем показывать заглушку в нашем iframe.
    var rtMatch = videoUrl.match(/rutube\.ru\/(?:video|play\/embed)\/([a-f0-9]+)/);
    if (rtMatch) {
      window.open('https://rutube.ru/video/' + rtMatch[1] + '/', '_blank', 'noopener');
      return;
    }

    var wrap = document.createElement('div');
    wrap.className = 'modal-bg rm-modal-overlay';
    // Inline-стили (на webapp нет .modal-bg CSS, поэтому используем явные)
    wrap.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.78);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;padding:1rem';
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap) wrap.remove();
    });

    var card = document.createElement('div');
    card.className = 'modal-card';
    // Inline-стили — на webapp нет .modal-card CSS
    card.style.cssText = 'max-width:1024px;width:95vw;max-height:92vh;overflow-y:auto;background:#0c0e15;border:1px solid rgba(255,255,255,.08);border-radius:20px;box-shadow:0 30px 80px -10px rgba(0,0,0,.8);padding:0';

    var head = document.createElement('div');
    head.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid rgba(255,255,255,.08);font-weight:600;color:#eef0f5';
    var titleSpan = document.createElement('span');
    titleSpan.textContent = title;
    titleSpan.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
    var closeBtn = document.createElement('button');
    closeBtn.textContent = '×';
    closeBtn.style.cssText = 'background:none;border:none;color:#8a90a1;font-size:26px;cursor:pointer;line-height:1;padding:0 8px';
    closeBtn.addEventListener('click', function () { wrap.remove(); });
    head.appendChild(titleSpan);
    head.appendChild(closeBtn);
    card.appendChild(head);

    var iframe = document.createElement('iframe');
    iframe.src = unwrapVideoUrl(videoUrl);
    iframe.setAttribute('allow', 'autoplay; encrypted-media; fullscreen; picture-in-picture');
    iframe.allowFullscreen = true;
    iframe.style.cssText = 'width:100%;aspect-ratio:16/9;border:none;background:#000;display:block';
    card.appendChild(iframe);

    wrap.appendChild(card);
    document.body.appendChild(wrap);
  }

  function makeBar(videos, title, includeHighlights) {
    var bar = document.createElement('div');
    bar.className = 'rm-videos-bar';
    bar.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;justify-content:center';

    var seen = {};
    for (var i = 0; i < videos.length; i++) {
      var v = videos[i];
      if (!includeHighlights && v.type === 'highlights') continue;
      if (seen[v.type]) continue;
      seen[v.type] = true;
      var btn = document.createElement('button');
      btn.className = 'chip gold-chip';
      btn.style.cursor = 'pointer';
      btn.style.padding = '6px 12px';
      btn.textContent = labelFor(v.type);
      (function (url, label, provider) {
        btn.addEventListener('click', function (ev) {
          ev.stopPropagation();
          ev.preventDefault();
          openModal(url, title + ' — ' + label.replace(/^▶ /, ''), provider);
        });
      })(v.url, labelFor(v.type), v.provider);
      bar.appendChild(btn);
    }
    return bar;
  }

  // SITE: список «Результаты»
  function tryBindSiteCards() {
    var rows = document.querySelectorAll('div.flex.items-center.gap-3.p-3.rounded-xl');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (row.dataset.videosBound === '1') continue;
      var imgs = row.querySelectorAll('img[alt]');
      if (imgs.length !== 2) continue;
      var home = imgs[0].alt, away = imgs[1].alt;
      var dateEl = row.querySelector('.text-xs.shrink-0') || row.querySelector('.text-xs');
      if (!dateEl) continue;
      var v = videosByDate[normDate(dateEl.textContent.trim())];
      if (!v) continue;
      row.dataset.videosBound = '1';
      var bar = makeBar(v, home + ' — ' + away, true);
      bar.style.padding = '6px 12px 10px';
      row.appendChild(bar);
    }
  }

  // Достаёт home + away team имена из hero-блока детальной страницы
  function extractTeamsFromHero(trigger) {
    var hero = trigger.closest('.match-hero') ||
               trigger.closest('div.glass.rounded-2xl');
    if (!hero) return null;
    var imgs = hero.querySelectorAll('img[alt]');
    if (imgs.length >= 2) {
      return { home: imgs[0].alt, away: imgs[1].alt };
    }
    var teamSpans = hero.querySelectorAll('.font-bold, span.text-sm.truncate, .truncate');
    if (teamSpans.length >= 2) {
      return { home: teamSpans[0].textContent.trim(), away: teamSpans[1].textContent.trim() };
    }
    return null;
  }

  function normTeam(s) {
    return String(s || '').toLowerCase().replace(/[^a-zа-я0-9]+/gi, '');
  }

  // Найти videos в кеше по home/away (любая дата с этими командами)
  function findVideosByTeams(home, away) {
    var nh = normTeam(home), na = normTeam(away);
    if (!nh || !na) return null;
    for (var d in videosByDate) {
      var arr = videosByDate[d];
      // Через первое попавшееся видео извлечь home/away невозможно — используем
      // отдельный кеш с home/away из results. Подгружаем результаты с командами:
    }
    return null;
  }

  // Расширенный кеш: дата → {videos, home, away}
  var matchByDate = {}; // нормализованные home/away для каждой даты
  function loadVideosV2() {
    return fetch('/api/matches/results', { credentials: 'omit' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var byDate = {}, info = {};
        var arr = (d && d.results) || [];
        for (var i = 0; i < arr.length; i++) {
          var x = arr[i];
          if (!x.videos || !x.videos.length) continue;
          var iso = normDate(x.date);
          byDate[iso] = x.videos;
          info[iso] = { home: x.home_team, away: x.away_team };
        }
        videosByDate = byDate;
        matchByDate = info;
      })
      .catch(function () {});
  }

  function findVideosForTeams(home, away) {
    var nh = normTeam(home), na = normTeam(away);
    for (var d in matchByDate) {
      var m = matchByDate[d];
      var mh = normTeam(m.home), ma = normTeam(m.away);
      if ((mh.indexOf(nh) !== -1 || nh.indexOf(mh) !== -1) &&
          (ma.indexOf(na) !== -1 || na.indexOf(ma) !== -1)) {
        return { date: d, videos: videosByDate[d] };
      }
    }
    return null;
  }

  function tryBindDetailPage() {
    if (!Object.keys(matchByDate).length) return;

    // WebApp: <a href="/api/embed/rutube/{id}">
    var trigger = document.querySelector('a[href*="/api/embed/rutube/"]');
    // Site: <button class="btn-gold">▶ Обзор матча</button>
    if (!trigger) {
      var allBtns = Array.from(document.querySelectorAll('button, a'));
      trigger = allBtns.find(function (el) {
        var t = (el.textContent || '');
        return /обзор\s*матча|смотреть\s*хайлайты|смотреть\s*обзор/i.test(t);
      });
    }
    if (!trigger || trigger.dataset.videosBound === '1') return;

    // Определяем матч: через rutube id из href ИЛИ через команды из hero
    var matchedDate = null, matchedVideos = null;

    var hrefM = (trigger.getAttribute('href') || '').match(/rutube\/([a-f0-9]+)|rutube\.ru\/(?:video|play\/embed)\/([a-f0-9]+)/);
    if (hrefM) {
      var rtId = hrefM[1] || hrefM[2];
      for (var d in videosByDate) {
        var found = videosByDate[d].some(function (x) {
          return x.url && x.url.indexOf(rtId) !== -1;
        });
        if (found) { matchedDate = d; matchedVideos = videosByDate[d]; break; }
      }
    }

    if (!matchedVideos) {
      var teams = extractTeamsFromHero(trigger);
      if (teams) {
        var f = findVideosForTeams(teams.home, teams.away);
        if (f) { matchedDate = f.date; matchedVideos = f.videos; }
      }
    }

    if (!matchedVideos) return;

    trigger.dataset.videosBound = '1';
    var hl = matchedVideos.find(function (v) { return v.type === 'highlights'; });

    // Перехват клика — открываем модал с Plyr плеером (для rutube) или iframe.
    // stopImmediatePropagation чтобы React-handler не открыл свой YouTube-модал поверх.
    trigger.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      ev.stopImmediatePropagation();
      if (hl && hl.url) openModal(hl.url, 'Обзор матча', hl.provider || 'rutube');
      else window.open(trigger.href || '#', '_blank', 'noopener');
    }, true);

    // Кнопки 1Т / 2Т / Полный матч — ТОЛЬКО на site. В WebApp пользователь
    // их явно не хочет на детальной странице.
    var isWebApp = !!document.querySelector('div.glass.rounded-2xl') ||
                   !!document.querySelector('a[href*="/api/embed/rutube/"]');
    if (isWebApp) return;

    var nonHL = matchedVideos.filter(function (v) { return v.type !== 'highlights'; });
    if (nonHL.length === 0) return;
    var bar = makeBar(nonHL, 'Запись матча', false);
    bar.style.padding = '8px 12px';
    bar.style.marginTop = '8px';
    var insertAfter = trigger.parentElement && /text-center/.test(trigger.parentElement.className || '')
      ? trigger.parentElement : trigger;
    insertAfter.insertAdjacentElement('afterend', bar);
  }

  // Защита от старого FAB из кеша браузера
  var oldFab = document.getElementById('rm-livetv-fab');
  if (oldFab) oldFab.remove();

  // ===== Live stream injection (webapp only) =====
  // Site рендерит StreamPlayer нативно в React-бандле; webapp нет.
  // Здесь — overlay-карточка для webapp.
  var IS_WEBAPP = /\/static\//.test((document.currentScript && document.currentScript.src) || '') ||
                  /^rm\./.test(location.hostname);

  function fetchStreams() {
    return fetch('/api/streams', { credentials: 'omit' })
      .then(function (r) { return r.json(); })
      .then(function (d) { return (d && d.streams) || []; })
      .catch(function () { return []; });
  }

  function buildStreamCard(stream) {
    var card = document.createElement('div');
    card.id = 'rm-livestream-card';
    card.style.cssText = 'margin:12px 12px 16px;border-radius:18px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);padding:14px;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)';

    var head = document.createElement('div');
    head.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px';

    var titleWrap = document.createElement('div');
    titleWrap.style.cssText = 'display:flex;align-items:center;gap:8px;min-width:0';
    var dot = document.createElement('span');
    dot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:#ff3b3b;box-shadow:0 0 8px #ff3b3b;animation:rm-live-pulse 1.4s ease-in-out infinite;flex:none';
    var titleText = document.createElement('span');
    titleText.textContent = stream.name || 'Прямая трансляция';
    titleText.style.cssText = 'font-weight:700;color:#eef0f5;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
    titleWrap.appendChild(dot);
    titleWrap.appendChild(titleText);

    var ext = document.createElement('a');
    ext.href = stream.url;
    ext.target = '_blank';
    ext.rel = 'noopener';
    ext.textContent = 'Открыть ↗';
    ext.style.cssText = 'color:#f4d57a;text-decoration:none;font-size:11px;white-space:nowrap;padding:4px 10px;border:1px solid rgba(244,213,122,.4);border-radius:8px';

    head.appendChild(titleWrap);
    head.appendChild(ext);
    card.appendChild(head);

    if (!document.getElementById('rm-live-style')) {
      var st = document.createElement('style');
      st.id = 'rm-live-style';
      st.textContent = '@keyframes rm-live-pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.55;transform:scale(1.25)}}';
      document.head.appendChild(st);
    }

    if (stream.type === 'hls' || stream.type === 'acestream') {
      // Для HLS/acestream нужен видео-плеер — webapp нативно не умеет.
      // Показываем заглушку с кнопкой «Открыть на сайте».
      var note = document.createElement('div');
      note.style.cssText = 'aspect-ratio:16/9;background:#000;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#8a90a1;font-size:13px;text-align:center;padding:16px';
      note.innerHTML = 'HLS-стрим. Открой на <br><a href="https://realmadrid.lead-seek.ru/" target="_blank" rel="noopener" style="color:#f4d57a">realmadrid.lead-seek.ru</a>';
      card.appendChild(note);
    } else {
      // iframe (default)
      var ifr = document.createElement('iframe');
      ifr.src = stream.url;
      ifr.allowFullscreen = true;
      ifr.setAttribute('allow', 'autoplay; encrypted-media; fullscreen; picture-in-picture');
      ifr.setAttribute('referrerpolicy', 'no-referrer');
      ifr.style.cssText = 'width:100%;aspect-ratio:16/9;border:none;background:#000;border-radius:12px;display:block';
      card.appendChild(ifr);
    }

    return card;
  }

  function injectStreamCard(streams) {
    var existing = document.getElementById('rm-livestream-card');

    if (!streams.length) {
      if (existing) existing.remove();
      return;
    }

    var s = streams[0]; // первый активный
    if (existing) {
      var ifr = existing.querySelector('iframe');
      if (ifr && ifr.src === s.url) return; // уже отрендерили этот URL
      existing.remove();
    }

    // Найти точку инжекта: над bottom-nav, внизу sticky header — обычно
    // первая большая карточка в #root после sticky header.
    var root = document.getElementById('root') || document.body;
    var firstBigCard = root.querySelector('.glass.rounded-2xl');
    var card = buildStreamCard(s);
    if (firstBigCard && firstBigCard.parentElement) {
      firstBigCard.parentElement.insertBefore(card, firstBigCard);
    } else {
      root.insertBefore(card, root.firstChild);
    }
  }

  var streamPollTimer = null;
  function startStreamPolling() {
    if (!IS_WEBAPP) return;
    if (streamPollTimer) return;
    var tick = function () {
      fetchStreams().then(injectStreamCard);
    };
    tick();
    streamPollTimer = setInterval(tick, 30 * 1000); // poll каждые 30с
  }

  function processRows() {
    if (!Object.keys(videosByDate).length) return;
    tryBindSiteCards();
    tryBindDetailPage();
    // WebApp список — кнопки НЕ показываем (по запросу пользователя).
    // Только на детальной странице каждого матча — tryBindDetailPage обрабатывает оба case'а.
  }

  var pendingTick = null;
  function scheduleProcess() {
    if (pendingTick) return;
    pendingTick = setTimeout(function () {
      pendingTick = null;
      processRows();
    }, 100);
  }

  var obs = new MutationObserver(scheduleProcess);
  obs.observe(document.body, { childList: true, subtree: true });

  loadVideosV2().then(processRows);
  setInterval(function () { loadVideosV2().then(processRows); }, 10 * 60 * 1000);

  startStreamPolling();
})();
