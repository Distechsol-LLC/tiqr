type SidebarController = {
  readonly isCollapsed: boolean;
  toggle: () => void;
};

const STORAGE_KEY = 'tiqr-sidebar';

const readStored = (): boolean => {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'collapsed';
  } catch {
    return false;
  }
};

// Collapsing only applies from the md breakpoint up; below it the sidebar is a top bar
const createSidebar = (): SidebarController => {
  let isCollapsed = $state(readStored());

  return {
    get isCollapsed(): boolean {
      return isCollapsed;
    },
    toggle: (): void => {
      isCollapsed = !isCollapsed;

      try {
        localStorage.setItem(STORAGE_KEY, isCollapsed ? 'collapsed' : 'expanded');
      } catch {
        // Storage can be blocked; the pick still holds for this visit
      }
    },
  };
};

const sidebar = createSidebar();

export { sidebar };
