import { useToast } from '../lib/toast';
import '../styles/toast.css';

/** Место для всплывающего сообщения (lib/toast.ts). */
export function Toaster() {
  const t = useToast();
  return (
    <div className="toaster" role="status" aria-live="polite">
      {t && (
        <div key={t.id} className="toast">
          {t.text}
        </div>
      )}
    </div>
  );
}
