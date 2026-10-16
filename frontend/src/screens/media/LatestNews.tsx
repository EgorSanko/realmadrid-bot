import { useNavigate } from 'react-router';
import { Card, SectionHeader, Skeleton } from '../../ui';
import { useApiResource } from '../../lib/apiResource';
import { NewsLink } from './MediaParts';
import type { NewsResponse } from './mediaData';
import './media.css';

export interface LatestNewsProps {
  /** сколько новостей показать; на главной по макету — 2 */
  limit?: number;
  className?: string;
}

/**
 * Блок «Новости» для главной: последние новости о «Реале» (строки с превью, как в a-home.html)
 * и ссылка «Все» в раздел «Медиа». Сам ходит в /api/news. Нет данных или ошибка — блок не
 * показывается (на главной это второстепенное, не стоит пугать ошибкой).
 */
export function LatestNews({ limit = 2, className }: LatestNewsProps) {
  const navigate = useNavigate();
  const { data, loading } = useApiResource<NewsResponse>(`/api/news?limit=${limit}`);
  if (!data && !loading) return null;
  const items = data?.items.slice(0, limit) ?? [];
  if (data && !items.length) return null;
  return (
    <Card ariaLabel="Новости" className={className}>
      <SectionHeader title="Новости" onAction={() => navigate('/media?tab=news')} />
      {loading && !data ? (
        <Skeleton shape="news" rows={limit} style={{ marginTop: 6 }} />
      ) : (
        items.map((n) => <NewsLink key={n.id} item={n} variant="row" />)
      )}
    </Card>
  );
}

export default LatestNews;
