// Набор интерфейсных компонентов стиля A («Ночной Бернабеу»).
// Пропсы — чистые данные, без привязки к ответам API.
import './ui.css';

export * from './base';
export * from './images';
export * from './match';
export * from './stats';
export * from './media';
export {
  formatKickoff,
  formatTime,
  formatDayShort,
  formatWeekdayShort,
  formatMinute,
  plural,
  type DateInput,
} from './format';
