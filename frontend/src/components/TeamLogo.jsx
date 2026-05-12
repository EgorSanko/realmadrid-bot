// src/components/TeamLogo.jsx — team crest with fallback initial.
import React from 'react';

export default function TeamLogo({ src, name, size = 40, className = '' }) {
  const [errored, setErrored] = React.useState(false);
  if (!src || errored) {
    const initial = (name || '?').trim().charAt(0).toUpperCase();
    return (
      <div
        className={`inline-flex items-center justify-center bg-zinc-700 text-zinc-300 rounded-full font-bold ${className}`}
        style={{ width: size, height: size, fontSize: size * 0.4 }}
      >
        {initial}
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={name || ''}
      loading="lazy"
      onError={() => setErrored(true)}
      className={`inline-block object-contain ${className}`}
      style={{ width: size, height: size }}
    />
  );
}
