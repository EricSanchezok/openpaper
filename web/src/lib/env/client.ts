import { z } from "zod";

const clientEnvironmentSchema = z.object({
  NEXT_PUBLIC_API_URL: z.string().url().default("http://127.0.0.1:7301"),
});

export const clientEnvironment = clientEnvironmentSchema.parse({
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
});
