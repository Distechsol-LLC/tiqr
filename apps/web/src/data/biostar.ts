import { z } from 'zod';

const biostarSchema = z.object({
  access_group_id: z.string(),
  base_url: z.string(),
  configured: z.boolean(),
  device_ids: z.array(z.string()),
  door_open_duration: z.number().int(),
  door_open_timeout: z.number().int(),
  has_password: z.boolean(),
  username: z.string(),
  verify_tls: z.boolean(),
});

const biostarDeviceSchema = z.object({
  address: z.string(),
  id: z.string(),
  name: z.string(),
  selected: z.boolean(),
  status: z.string(),
});

const biostarLogSchema = z.object({
  direction: z.string().nullable(),
  event_id: z.string(),
  event_time: z.string(),
  granted: z.boolean(),
  outcome: z.string(),
  point_id: z.string().nullable(),
  point_name: z.string().nullable(),
});

type Biostar = z.infer<typeof biostarSchema>;
type BiostarDevice = z.infer<typeof biostarDeviceSchema>;
type BiostarLog = z.infer<typeof biostarLogSchema>;

// A blank password keeps the saved one
type BiostarInput = {
  base_url: string;
  device_ids: string[];
  password: string;
  username: string;
  verify_tls: boolean;
};

export type { Biostar, BiostarDevice, BiostarInput, BiostarLog };
export { biostarDeviceSchema, biostarLogSchema, biostarSchema };
