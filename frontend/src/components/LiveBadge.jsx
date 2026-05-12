// src/components/LiveBadge.jsx — pulsing "LIVE" indicator.
import React from 'react';

export default function LiveBadge({ minute }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-red-600 rounded text-xs font-semibold uppercase">
      <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse" />
      LIVE{typeof minute === 'number' ? ` ${minute}'` : ''}
    </span>
  );
}
