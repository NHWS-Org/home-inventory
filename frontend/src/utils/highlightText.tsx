import type { ReactNode } from 'react';

function renderParts(parts: string[]): ReactNode {
  return parts.map((part, index) => index % 2 === 1 ? (
    <span key={index} className="rounded-sm bg-blue-100 px-0.5 text-gray-900 dark:bg-blue-800 dark:text-white">{part}</span>
  ) : part);
}

export function renderHighlightedText(text: string): ReactNode {
  return renderParts(text.split(/\*\*(.*?)\*\*/g));
}

export function highlightSearchText(text: string, search: string): ReactNode {
  if (!search) return text;
  const escaped = search.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return renderParts(text.split(new RegExp(`(${escaped})`, 'gi')));
}
