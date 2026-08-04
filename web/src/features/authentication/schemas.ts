import { z } from "zod";

export type AuthValidationMessages = {
  displayNameMaximum: string;
  email: string;
  passwordConfirmationRequired: string;
  passwordRequired: string;
  passwordMinimum: string;
  passwordMismatch: string;
  tokenRequired: string;
};

export function createAuthSchemas(messages: AuthValidationMessages) {
  const email = z.string().trim().email(messages.email);
  const password = z.string().min(1, messages.passwordRequired);
  const newPassword = z.string().min(12, messages.passwordMinimum);
  const token = z.string().min(1, messages.tokenRequired);

  return {
    signIn: z.object({ email, password }),
    register: z
      .object({
        displayName: z
          .string()
          .trim()
          .max(120, messages.displayNameMaximum)
          .optional(),
        email,
        password: newPassword,
        confirmPassword: z
          .string()
          .min(1, messages.passwordConfirmationRequired),
      })
      .refine(
        (value) =>
          value.confirmPassword.length === 0 ||
          value.password === value.confirmPassword,
        {
          message: messages.passwordMismatch,
          path: ["confirmPassword"],
        },
      )
      .transform((value) => ({
        display_name: value.displayName || undefined,
        email: value.email,
        password: value.password,
      })),
    forgotPassword: z.object({ email }),
    resetPassword: z
      .object({
        token,
        newPassword,
        confirmPassword: z
          .string()
          .min(1, messages.passwordConfirmationRequired),
      })
      .refine(
        (value) =>
          value.confirmPassword.length === 0 ||
          value.newPassword === value.confirmPassword,
        {
          message: messages.passwordMismatch,
          path: ["confirmPassword"],
        },
      )
      .transform((value) => ({
        token: value.token,
        new_password: value.newPassword,
      })),
    verifyEmail: z.object({ token }),
    resendVerification: z.object({ email }),
  };
}
