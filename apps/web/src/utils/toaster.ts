import { createToaster } from '@skeletonlabs/skeleton-svelte';

// One toaster for the app; App.svelte renders its Toast.Group. Top stays clear of mobile keyboards.
export const toaster = createToaster({ overlap: true, placement: 'bottom-end' });
