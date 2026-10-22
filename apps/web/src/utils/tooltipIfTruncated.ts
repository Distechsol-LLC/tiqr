// Titles the element with its text only while the table cuts that text short, so the tooltip shows all of it
export const tooltipIfTruncated = (element: HTMLElement): (() => void) => {
  const sync = (): void => {
    if (element.scrollWidth > element.clientWidth) {
      element.title = (element.textContent ?? '').replace(/\s+/g, ' ').trim();
    } else {
      element.removeAttribute('title');
    }
  };

  // Width changes with the window and the columns; the text changes with the page
  const resizes = new ResizeObserver(sync);
  const mutations = new MutationObserver(sync);

  resizes.observe(element);
  mutations.observe(element, {
    characterData: true,
    childList: true,
    subtree: true,
  });

  return (): void => {
    resizes.disconnect();
    mutations.disconnect();
  };
};
