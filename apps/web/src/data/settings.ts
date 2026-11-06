import { z } from 'zod';

// What the install issues; each mode keeps its own database on the server
const modeSchema = z.enum(['ticket', 'badge']);

// What GET and PUT /api/settings/mode send. Pinned when TIQR_MODE is set in the server's
// environment, which a switch from here can't override
const modeStateSchema = z.object({
  mode: modeSchema,
  pinned: z.boolean(),
});

type Mode = z.infer<typeof modeSchema>;
type ModeState = z.infer<typeof modeStateSchema>;

export type { Mode, ModeState };
export { modeSchema, modeStateSchema };
