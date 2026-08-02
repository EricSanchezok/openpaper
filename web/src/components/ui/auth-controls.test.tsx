import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button, LinkButton } from "./button";
import {
  Field,
  FieldControl,
  FieldDescription,
  FieldLabel,
  FieldMessage,
} from "./field";
import { Input, PasswordInput } from "./input";

describe("authentication controls", () => {
  it("associates the field label, description, error, and control", () => {
    render(
      <Field invalid>
        <FieldLabel>Email</FieldLabel>
        <FieldControl>
          <Input />
        </FieldControl>
        <FieldDescription>Account address</FieldDescription>
        <FieldMessage>Enter a valid email</FieldMessage>
      </Field>,
    );

    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(
      "Account address Enter a valid email",
    );
  });

  it("does not submit while a button is loading", async () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Continue
      </Button>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("prevents disabled link navigation", async () => {
    const onClick = vi.fn();
    render(
      <LinkButton disabled href="#target" onClick={onClick}>
        Continue
      </LinkButton>,
    );
    const link = screen.getByRole("link", { name: "Continue" });
    await userEvent.click(link);
    expect(onClick).not.toHaveBeenCalled();
    expect(link).toHaveAttribute("aria-disabled", "true");
  });

  it("toggles password visibility with a localized label", async () => {
    render(
      <PasswordInput
        defaultValue="twelve-characters"
        hidePasswordLabel="Hide password"
        showPasswordLabel="Show password"
      />,
    );
    const input = screen.getByDisplayValue("twelve-characters");
    expect(input).toHaveAttribute("type", "password");
    await userEvent.click(
      screen.getByRole("button", { name: "Show password" }),
    );
    expect(input).toHaveAttribute("type", "text");
  });
});
