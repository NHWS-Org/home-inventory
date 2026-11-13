export function scrollPageToTop(element: HTMLElement): void {
  const container = element.closest<HTMLElement>('[data-page-scroll]');
  (container ?? window).scrollTo({ top: 0, behavior: 'smooth' });
}
