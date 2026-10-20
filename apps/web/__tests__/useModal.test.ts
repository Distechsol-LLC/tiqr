import { afterEach, describe, expect, test as it } from 'bun:test';

import { type ModalOptions, modalHost, useModal } from '%/useModal.svelte.ts';

const child = {} as ModalOptions['child'];

describe('useModal', () => {
  afterEach(() => {
    modalHost.current?.close();
  });

  it('shows the modal on the host until it closes', () => {
    const modal = useModal({ child });

    modal.open();

    expect(modal.isOpen).toBeTrue();
    expect(modalHost.current).toBe(modal);

    modal.close();

    expect(modal.isOpen).toBeFalse();
    expect(modalHost.current).toBeNull();
  });

  it('closes the modal it replaces', () => {
    const first = useModal({ child });
    const second = useModal({ child });

    first.open();
    second.open();

    expect(first.isOpen).toBeFalse();
    expect(second.isOpen).toBeTrue();
    expect(modalHost.current).toBe(second);
  });

  it('leaves the host alone when a replaced modal closes', () => {
    const first = useModal({ child });
    const second = useModal({ child });

    first.open();
    second.open();
    first.close();

    expect(modalHost.current).toBe(second);
  });

  it('keeps the settings it was given', () => {
    const modal = useModal({ ariaLabel: 'Ticket', child, isClosable: false });

    expect(modal.settings).toEqual({ ariaLabel: 'Ticket', isClosable: false });
  });
});
