/** Английский словарь целиком — грузится отдельным чанком только при английском языке (main.tsx). */
import api from './api';
import common from './common';
import games from './games';
import home from './home';
import legal from './legal';
import match from './match';
import matches from './matches';
import media from './media';
import player from './player';
import predict from './predict';
import profile from './profile';
import shell from './shell';
import team from './team';

const en: Record<string, string> = {
  ...common, ...shell, ...home, ...match, ...matches, ...predict, ...games, ...profile, ...team, ...player, ...media,
  ...legal, ...api,
};

export default en;
