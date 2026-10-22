import { delegate } from 'tippy.js';
import 'tippy.js/dist/tippy.css';
import 'tippy.js/dist/border.css';

const TOOLTIP_TARGETS = '[title]';
const SHOW_DELAY = 500;
const HIDE_DELAY = 150;

export const useTooltip = (): (() => void) => {
  const tooltips = delegate(document.body, {
    arrow: false,
    content: (reference) => reference.getAttribute('title') ?? '',
    delay: [SHOW_DELAY, HIDE_DELAY],
    // Nothing to say: the element dropped its title since this tooltip was made
    onShow: (instance) => {
      if (instance.props.content === '') return false;
    },
    onTrigger: (instance) => {
      // removes native title popup
      const title = instance.reference.getAttribute('title');

      instance.setContent(title ?? '');
      instance.reference.removeAttribute('title');
    },
    // Hand the title back, so a later change or removal of it is seen on the next trigger
    onUntrigger: (instance) => {
      const { content } = instance.props;

      if (typeof content === 'string' && content !== '')
        instance.reference.setAttribute('title', content);
    },
    target: TOOLTIP_TARGETS,
    theme: 'tiqr',
    touch: ['hold', HIDE_DELAY], // touch delay
  });

  return (): void => {
    tooltips.destroy();
  };
};
