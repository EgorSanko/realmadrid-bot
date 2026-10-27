/**
 * Английские строки: legal. Ключ — русский текст из t()/plural(), значение — перевод (подстановки {имя} те же).
 * Сами тексты политики и условий по-английски — отдельной JSX-редакцией в screens/legal/LegalScreen.tsx (PrivacyEn, TermsEn).
 */
const en: Record<string, string> = {
  'Условия использования': 'Terms of use',
  '{title} — Мадридиста': '{title} — Madridista',
  'Назад': 'Back',
  'Редакция от {date}': 'Last updated: {date}',
};

export default en;
