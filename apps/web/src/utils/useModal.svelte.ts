import type { Component } from 'svelte';

type ModalChild = Component<{ onClose: () => void }>;

// Modal settings the caller picks; open state and close belong to the controller
type ModalSettings = {
  ariaLabel?: string;
  isClosable?: boolean;
  onSubmit?: (event: SubmitEvent) => void | Promise<void>;
};

type ModalOptions = ModalSettings & {
  child: ModalChild;
};

type ModalController = {
  readonly isOpen: boolean;
  readonly child: ModalChild;
  readonly settings: ModalSettings;
  open: () => void;
  close: () => void;
};

// $state.raw keeps the controller itself, so the identity checks below hold
let active = $state.raw<ModalController | null>(null);

const modalHost = {
  get current(): ModalController | null {
    return active;
  },
  set current(next: ModalController | null) {
    active = next;
  },
};

const useModal = ({ child, ...settings }: ModalOptions): ModalController => {
  let isOpen = $state(false);

  const controller: ModalController = {
    child,
    close: (): void => {
      isOpen = false;

      if (modalHost.current === controller) modalHost.current = null;
    },
    get isOpen(): boolean {
      return isOpen;
    },
    open: (): void => {
      // One modal shows at a time, so the one being replaced closes first
      modalHost.current?.close();
      isOpen = true;
      modalHost.current = controller;
    },
    settings,
  };

  return controller;
};

export type { ModalOptions };
export { modalHost, useModal };
