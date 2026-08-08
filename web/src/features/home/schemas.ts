import { z } from "zod";

export const composerSchema = z.object({
  message: z.string().trim().min(1).max(20_000),
});

export type ComposerValues = z.infer<typeof composerSchema>;
