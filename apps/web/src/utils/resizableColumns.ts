// Gives each header cell a handle on its right edge, so dragging it sets that column's width
// Browsers ignore min-width on table cells, so the drag stops at the cell's own min-width here, or the default
// Handles belong to the table, not the cell: the cell clips what overflows it, and the handle straddles the edge
const DEFAULT_MIN_WIDTH = 96;
const HANDLE_CLASS =
  'absolute z-10 w-1 -translate-x-1/2 cursor-col-resize touch-none hover:bg-primary-500/40';
const HANDLE_SELECTOR = 'span[data-resize-handle]';

// Columns move as others are dragged, so each handle is put back on its cell's right edge
const placeHandles = (table: HTMLTableElement): void => {
  for (const cell of table.tHead?.rows[0]?.cells ?? []) {
    const handle = cell.querySelector<HTMLElement>(HANDLE_SELECTOR);
    if (!handle) {
      continue;
    }
    handle.style.left = `${cell.offsetLeft + cell.offsetWidth}px`;
    handle.style.top = `${cell.offsetTop}px`;
    handle.style.height = `${cell.offsetHeight}px`;
  }
};

const addHandles = (table: HTMLTableElement): void => {
  for (const cell of table.tHead?.rows[0]?.cells ?? []) {
    // The actions column is sized to its buttons, so it can't be dragged
    if (cell.hasAttribute('data-fixed') || cell.querySelector(HANDLE_SELECTOR)) {
      continue;
    }
    const handle = document.createElement('span');
    handle.className = HANDLE_CLASS;
    handle.dataset.resizeHandle = '';
    handle.setAttribute('aria-hidden', 'true');
    handle.addEventListener('pointerdown', (event) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = cell.getBoundingClientRect().width;
      const minWidth = parseFloat(getComputedStyle(cell).minWidth) || DEFAULT_MIN_WIDTH;
      handle.setPointerCapture(event.pointerId);

      const move = (moved: PointerEvent): void => {
        cell.style.width = `${Math.max(minWidth, startWidth + moved.clientX - startX)}px`;
        placeHandles(table);
      };
      const stop = (): void => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', stop);
        handle.removeEventListener('pointercancel', stop);
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', stop);
      handle.addEventListener('pointercancel', stop);
    });
    cell.append(handle);
  }
  placeHandles(table);
};

// Columns come and go with the page, so the handles are added again when the head changes
export const resizableColumns = (table: HTMLTableElement): (() => void) | undefined => {
  const head = table.tHead;
  if (!head) {
    return;
  }

  addHandles(table);
  const mutations = new MutationObserver(() => {
    addHandles(table);
  });
  mutations.observe(head, { childList: true, subtree: true });

  // The table grows and shrinks with its columns, which moves the handles along with it
  const sizes = new ResizeObserver(() => {
    placeHandles(table);
  });
  sizes.observe(table);

  return (): void => {
    mutations.disconnect();
    sizes.disconnect();
  };
};
