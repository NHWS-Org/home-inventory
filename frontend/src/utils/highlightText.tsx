import type { ReactNode } from 'react';

function renderParts(parts: string[]): ReactNode {
  return parts.map((part, index) => index % 2 === 1 ? (
    <mark key={index} className="rounded-sm bg-yellow-300 px-0.5 font-bold text-gray-950 ring-1 ring-inset ring-amber-600 dark:bg-yellow-300 dark:text-gray-950 dark:ring-yellow-200">{part}</mark>
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
