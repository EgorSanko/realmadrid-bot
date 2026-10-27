import { useCallback, useEffect } from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { isEn, t } from '../../lib/i18n';
import { useSpaLink } from '../../lib/spaLink';
import { useTelegramBackButton } from '../../lib/tmaNav';
import './legal.css';

/*
 * Документы: политика конфиденциальности (/privacy) и условия использования (/terms).
 * Нужны магазину приложений (RuStore) и сайту. Текст простой, по-русски (английская редакция — PrivacyEn / TermsEn); при изменении — обновить дату.
 */

const UPDATED = '20 октября 2026 г.';
/** та же дата по-английски — менять вместе с UPDATED */
const UPDATED_EN = 'October 20, 2026';
const BOT = 'Real_Madrid_football_bot';
const BOT_LINK = `https://t.me/${BOT}`;

const BACK_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

function Privacy() {
  const link = useSpaLink();
  return (
    <>
      <p className="lg-lead">
        «Мадридиста» — неофициальное фанатское приложение и сайт о футбольном клубе «Реал Мадрид»
        (realmadridfan.ru, Android-приложение «Мадридиста» и мини-приложение в Telegram). Мы не связаны с Real
        Madrid C.F. и не представляем клуб. Здесь простыми словами написано, какие данные мы храним, зачем и как их
        удалить.
      </p>

      <h2>1. Без входа</h2>
      <p>
        Все разделы — матчи, таблицы, состав, игроки, новости, видео, викторина и пенальти — открываются без
        регистрации. Пока вы не вошли, мы не храним о вас ничего, кроме анонимного счётчика посещений (ниже) и обычных
        технических журналов сервера (см. п. 5). Рекламы и сторонних систем аналитики нет. Push-уведомлений нет: бот
        никому не пишет первым.
      </p>
      <p>
        <b>Счётчик посещений.</b> Чтобы знать, сколько людей заходит каждый день, приложение хранит на устройстве
        случайный идентификатор и раз в день сообщает серверу, что открывалось, и где — сайт, Telegram или
        Android-приложение. Сервер хранит не сам идентификатор, а его необратимый хеш и дату; IP-адрес и сведения об
        устройстве к нему не записываются. Если вы вошли, к записи добавляется ваш Telegram ID (при удалении аккаунта
        связь стирается). Эти данные видит только владелец сервиса в виде общих чисел и никому не передаёт.
      </p>

      <h2>2. Что мы храним после входа</h2>
      <p>Вход нужен только для прогнозов, рейтингов, лиг с друзьями и сохранения результатов игр. Вход — через Telegram (бот @{BOT}); пароль мы не спрашиваем и не храним. После входа сохраняются:</p>
      <ul>
        <li>
          <b>данные профиля Telegram</b>: числовой идентификатор (Telegram ID), имя и фамилия, имя пользователя
          (@username), если они указаны, и фотография профиля — её копию мы храним на своём сервере, чтобы показывать
          в профиле и рейтинге;
        </li>
        <li>
          <b>ваши действия в приложении</b>: прогнозы на матчи и начисленные очки, места в рейтингах, созданные лиги и
          участие в них, результаты викторины и пенальти;
        </li>
        <li>
          <b>служебные данные</b>: время создания профиля и последнего визита (не чаще раза в сутки); cookie сессии{' '}
          <code>rm_session</code> — она держит вас в аккаунте до 30 дней или до нажатия «Выйти»; на время входа по коду —
          одноразовый код и cookie <code>rm_login</code> (живут 5 минут, затем удаляются).
        </li>
      </ul>
      <p>
        Ваше имя (в сокращённом виде, например «Лука М.»), фото и очки видны другим пользователям в рейтингах и в
        лигах, где вы участвуете. Больше никому эти данные не передаются и не продаются.
      </p>
      <p>
        В браузере или приложении на устройстве хранятся также настройки интерфейса (например, громкость) — они не
        покидают устройство.
      </p>

      <h2>3. Зачем</h2>
      <ul>
        <li>чтобы вы могли войти и оставаться в аккаунте;</li>
        <li>чтобы сохранять прогнозы, считать очки и показывать рейтинги и лиги;</li>
        <li>чтобы сохранять результаты игр и показывать рейтинг недели;</li>
        <li>чтобы защищать сервис от злоупотреблений (ограничение числа попыток входа).</li>
      </ul>

      <h2>4. Сколько храним</h2>
      <ul>
        <li>профиль, прогнозы, лиги и результаты игр — пока вы пользуетесь сервисом или пока не удалите аккаунт;</li>
        <li>копию фото профиля удаляем, если вы не заходили 180 дней (при следующем входе она появится снова);</li>
        <li>коды входа — 5 минут; cookie сессии — до 30 дней;</li>
        <li>отметки посещений по дням — 400 дней (дата первого посещения устройства — для общего числа людей);</li>
        <li>технические журналы сервера — до 14 дней.</li>
      </ul>

      <h2>5. Технические журналы</h2>
      <p>
        Как любой сайт, наш сервер записывает в журналы IP-адрес, время, адрес запрошенной страницы и тип браузера.
        Они нужны только для работы и защиты сервера, ни с кем не делятся и удаляются автоматически.
      </p>

      <h2>6. Сторонние сервисы</h2>
      <ul>
        <li>
          <b>Telegram</b> — вход через бота @{BOT}. Telegram передаёт нам только ваш ID, имя, username и фото профиля.
          Правила Telegram: <Ext href="https://telegram.org/privacy">telegram.org/privacy</Ext>.
        </li>
        <li>
          <b>Данные о матчах</b> (расписание, счёт, составы, статистика) наш сервер получает из открытых источников —
          FotMob, SofaScore, ESPN; новости — из «Чемпионата», «Спорт-Экспресса» и Sports.ru. Ваши данные этим сервисам
          не передаются.
        </li>
        <li>
          <b>Картинки</b> (эмблемы, фото игроков, флаги, превью видео и новостей) загружаются через наш сервер — ваше
          устройство не обращается к чужим сайтам за ними.
        </li>
        <li>
          <b>YouTube</b> — видео на странице видео встроены плеером YouTube в режиме повышенной конфиденциальности
          (youtube-nocookie.com). Он загружается, только когда вы открываете видео; при просмотре действуют правила
          Google: <Ext href="https://policies.google.com/privacy">policies.google.com/privacy</Ext>.
        </li>
      </ul>

      <h2>7. Как удалить данные</h2>
      <p>
        В разделе <a {...link('/profile')}>«Профиль»</a> нажмите «Удалить аккаунт» и подтвердите. Сразу и безвозвратно
        удалятся профиль, фото, прогнозы и очки, места в рейтингах, созданные вами лиги, участие в лигах, результаты
        игр и сессии входа. Выйти из аккаунта без удаления — кнопка «Выйти» там же. Если удалить самостоятельно не
        получается, напишите боту <Ext href={BOT_LINK}>@{BOT}</Ext> — удалим вручную.
      </p>

      <h2>8. Дети</h2>
      <p>
        Сервис рассчитан на широкую аудиторию болельщиков и не собирает данные о возрасте. Вход возможен только через
        Telegram, по его правилам.
      </p>

      <h2>9. Товарные знаки</h2>
      <p>
        «Реал Мадрид», Real Madrid, эмблема клуба и другие товарные знаки, названия и логотипы клубов и турниров
        принадлежат их правообладателям и используются только для того, чтобы показывать информацию о матчах. Это
        неофициальный проект болельщиков.
      </p>

      <h2>10. Контакты и изменения</h2>
      <p>
        Вопросы о данных — в Telegram-бот <Ext href={BOT_LINK}>@{BOT}</Ext>. Если политика изменится, новая версия
        появится на этой странице с новой датой.
      </p>
    </>
  );
}

function Terms() {
  const link = useSpaLink();
  return (
    <>
      <p className="lg-lead">
        «Мадридиста» — бесплатное неофициальное фанатское приложение и сайт о «Реале Мадрид». Пользуясь им, вы
        соглашаетесь с этими простыми условиями.
      </p>

      <h2>1. Что это</h2>
      <p>
        Информационный сервис для болельщиков: матчи, таблицы, состав, новости, видео, прогнозы на счёт и мини-игры.
        Проект не связан с Real Madrid C.F., Ла Лигой, УЕФА и другими организациями; их названия и знаки принадлежат
        правообладателям.
      </p>

      <h2>2. Бесплатно и без ставок</h2>
      <p>
        Прогнозы и игры — развлечение: очки ничего не стоят, их нельзя купить, вывести или обменять. Платежей, ставок и
        рекламы в сервисе нет.
      </p>

      <h2>3. Данные о матчах</h2>
      <p>
        Счёт, составы, статистику и новости мы берём из открытых источников и показываем как есть. Возможны задержки и
        ошибки; официальную информацию смотрите на сайтах клуба и турниров.
      </p>

      <h2>4. Поведение</h2>
      <p>
        Не пытайтесь нарушить работу сервиса, подобрать чужие коды или обойти ограничения. Названия лиг не должны быть
        оскорбительными — такие лиги мы можем удалить.
      </p>

      <h2>5. Аккаунт</h2>
      <p>
        Вход — через Telegram. Удалить аккаунт и все данные можно в любой момент в разделе «Профиль». Как мы обращаемся
        с данными — в <a {...link('/privacy')}>политике конфиденциальности</a>.
      </p>

      <h2>6. Контакты</h2>
      <p>
        Вопросы и предложения — в Telegram-бот <Ext href={BOT_LINK}>@{BOT}</Ext>.
      </p>
    </>
  );
}

/*
 * Английская редакция тех же документов (isEn()). Смысл — один в один с русской; при изменении русского текста
 * обновить и её. Реквизиты, адреса, имена бота и cookie не переводятся.
 */
function PrivacyEn() {
  const link = useSpaLink();
  return (
    <>
      <p className="lg-lead">
        Madridista is an unofficial fan app and website about Real Madrid football club (realmadridfan.ru, the
        Madridista Android app and the Telegram mini app). We are not affiliated with Real Madrid C.F. and do not
        represent the club. This page explains in plain words what data we store, why, and how to delete it.
      </p>

      <h2>1. Without signing in</h2>
      <p>
        All sections — matches, tables, squad, players, news, videos, the quiz and the penalty game — open without
        registration. Until you sign in, we store nothing about you except an anonymous visit counter (below) and the
        usual technical server logs (see section 5). There are no ads and no third-party analytics. There are no push
        notifications: the bot never messages anyone first.
      </p>
      <p>
        <b>Visit counter.</b> To know how many people visit each day, the app stores a random identifier on your
        device and once a day tells the server what was opened and where — the website, Telegram or the Android app.
        The server stores not the identifier itself but its irreversible hash and the date; no IP address or device
        information is recorded with it. If you are signed in, your Telegram ID is added to the record (the link is
        erased when you delete your account). This data is seen only by the owner of the service, as aggregate
        numbers, and is not shared with anyone.
      </p>

      <h2>2. What we store after you sign in</h2>
      <p>
        Signing in is needed only for predictions, leaderboards, leagues with friends and saving game results. You sign
        in via Telegram (the bot @{BOT}); we never ask for or store a password. After you sign in, we keep:
      </p>
      <ul>
        <li>
          <b>Telegram profile data</b>: your numeric identifier (Telegram ID), first and last name, username
          (@username), if set, and your profile photo — we keep a copy of it on our server to show it in your profile
          and on leaderboards;
        </li>
        <li>
          <b>your activity in the app</b>: match predictions and points awarded, leaderboard positions, leagues you
          created and joined, quiz and penalty game results;
        </li>
        <li>
          <b>service data</b>: when your profile was created and your last visit (recorded at most once a day); the
          session cookie <code>rm_session</code> — it keeps you signed in for up to 30 days or until you tap “Log
          out”; while you sign in with a code — a one-time code and the cookie <code>rm_login</code> (they live for 5
          minutes and are then deleted).
        </li>
      </ul>
      <p>
        Your name (in short form, e.g. “Luka M.”), photo and points are visible to other users on leaderboards and in
        the leagues you take part in. This data is not shared with or sold to anyone else.
      </p>
      <p>
        Interface settings (for example, volume) are also stored in the browser or the app on your device — they never
        leave the device.
      </p>

      <h2>3. Why</h2>
      <ul>
        <li>so that you can sign in and stay signed in;</li>
        <li>to save predictions, calculate points and show leaderboards and leagues;</li>
        <li>to save game results and show the weekly leaderboard;</li>
        <li>to protect the service from abuse (limiting the number of sign-in attempts).</li>
      </ul>

      <h2>4. How long we keep it</h2>
      <ul>
        <li>profile, predictions, leagues and game results — while you use the service or until you delete your account;</li>
        <li>the copy of your profile photo is deleted if you have not visited for 180 days (it reappears the next time you sign in);</li>
        <li>sign-in codes — 5 minutes; the session cookie — up to 30 days;</li>
        <li>daily visit records — 400 days (the date of a device’s first visit is kept for the total number of people);</li>
        <li>technical server logs — up to 14 days.</li>
      </ul>

      <h2>5. Technical logs</h2>
      <p>
        Like any website, our server records the IP address, time, requested page address and browser type in its
        logs. They are needed only to run and protect the server, are not shared with anyone and are deleted
        automatically.
      </p>

      <h2>6. Third-party services</h2>
      <ul>
        <li>
          <b>Telegram</b> — sign-in via the bot @{BOT}. Telegram passes us only your ID, name, username and profile
          photo. Telegram’s policy: <Ext href="https://telegram.org/privacy">telegram.org/privacy</Ext>.
        </li>
        <li>
          <b>Match data</b> (fixtures, scores, lineups, statistics) is obtained by our server from public sources —
          FotMob, SofaScore, ESPN; news — from Championat, Sport-Express and Sports.ru. Your data is not passed to these
          services.
        </li>
        <li>
          <b>Images</b> (crests, player photos, flags, video and news previews) are loaded through our server — your
          device does not contact other websites for them.
        </li>
        <li>
          <b>YouTube</b> — videos on the video page are embedded with the YouTube player in privacy-enhanced mode
          (youtube-nocookie.com). It loads only when you open a video; while watching, Google’s policy applies:{' '}
          <Ext href="https://policies.google.com/privacy">policies.google.com/privacy</Ext>.
        </li>
      </ul>

      <h2>7. How to delete your data</h2>
      <p>
        In the <a {...link('/profile')}>“Profile”</a> section, tap “Delete account” and confirm. Your profile, photo,
        predictions and points, leaderboard positions, leagues you created, league memberships, game results and
        sign-in sessions are deleted immediately and permanently. To log out without deleting, use the “Log out”
        button in the same place. If you can’t delete it yourself, message the bot <Ext href={BOT_LINK}>@{BOT}</Ext>{' '}
        and we will delete it manually.
      </p>

      <h2>8. Children</h2>
      <p>
        The service is intended for a broad audience of fans and does not collect age data. Sign-in is possible only
        via Telegram, under its rules.
      </p>

      <h2>9. Trademarks</h2>
      <p>
        “Real Madrid”, the club crest and other trademarks, names and logos of clubs and competitions belong to their
        respective owners and are used only to display match information. This is an unofficial fan project.
      </p>

      <h2>10. Contacts and changes</h2>
      <p>
        Questions about your data — to the Telegram bot <Ext href={BOT_LINK}>@{BOT}</Ext>. If the policy changes, the
        new version will appear on this page with a new date.
      </p>
    </>
  );
}

function TermsEn() {
  const link = useSpaLink();
  return (
    <>
      <p className="lg-lead">
        Madridista is a free, unofficial fan app and website about Real Madrid. By using it, you agree to these simple
        terms.
      </p>

      <h2>1. What it is</h2>
      <p>
        An information service for fans: matches, tables, squad, news, videos, score predictions and mini games. The
        project is not affiliated with Real Madrid C.F., LaLiga, UEFA or other organizations; their names and marks
        belong to their respective owners.
      </p>

      <h2>2. Free and no betting</h2>
      <p>
        Predictions and games are just for fun: points have no value and cannot be bought, withdrawn or exchanged.
        There are no payments, bets or ads in the service.
      </p>

      <h2>3. Match data</h2>
      <p>
        We take scores, lineups, statistics and news from public sources and show them as is. Delays and errors are
        possible; for official information, see the websites of the club and the competitions.
      </p>

      <h2>4. Conduct</h2>
      <p>
        Do not try to disrupt the service, guess other people’s codes or bypass limits. League names must not be
        offensive — we may delete such leagues.
      </p>

      <h2>5. Account</h2>
      <p>
        You sign in via Telegram. You can delete your account and all your data at any time in the “Profile” section.
        How we handle data is described in the <a {...link('/privacy')}>privacy policy</a>.
      </p>

      <h2>6. Contacts</h2>
      <p>
        Questions and suggestions — to the Telegram bot <Ext href={BOT_LINK}>@{BOT}</Ext>.
      </p>
    </>
  );
}

export default function LegalScreen({ doc }: { doc: 'privacy' | 'terms' }) {
  const navigate = useNavigate();
  const title = doc === 'privacy' ? t('Политика конфиденциальности') : t('Условия использования');

  const goBack = useCallback(() => {
    const idx = (window.history.state as { idx?: number } | null)?.idx;
    if (!idx) navigate('/profile', { replace: true });
    else navigate(-1);
  }, [navigate]);
  const nativeBack = useTelegramBackButton(goBack);

  useEffect(() => {
    document.title = t('{title} — Мадридиста', { title });
  }, [title]);

  return (
    <main className="lg">
      <header className="lg-top">
        {nativeBack ? (
          <span className="lg-top__gap" aria-hidden="true" />
        ) : (
          <button type="button" className="lg-top__back" aria-label={t('Назад')} onClick={goBack}>
            {BACK_ICON}
          </button>
        )}
        <span className="lg-top__brand">{t('Мадридиста')}</span>
        <span className="lg-top__gap" aria-hidden="true" />
      </header>
      <article className="lg-doc">
        <h1>{title}</h1>
        <p className="lg-date">{t('Редакция от {date}', { date: isEn() ? UPDATED_EN : UPDATED })}</p>
        {isEn() ? doc === 'privacy' ? <PrivacyEn /> : <TermsEn /> : doc === 'privacy' ? <Privacy /> : <Terms />}
      </article>
    </main>
  );
}
