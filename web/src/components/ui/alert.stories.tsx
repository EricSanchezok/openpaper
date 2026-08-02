import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Alert, AlertDescription, AlertTitle } from "./alert";

const meta = {
  title: "Feedback/Alert",
  component: Alert,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: { tone: "neutral" },
  argTypes: {
    tone: {
      control: "select",
      options: ["neutral", "info", "success", "warning", "danger"],
    },
  },
} satisfies Meta<typeof Alert>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {
  render: (args) => (
    <Alert className="w-[min(90vw,30rem)]" {...args}>
      <AlertTitle>Authentication status</AlertTitle>
      <AlertDescription>
        Additional context remains readable and localizable.
      </AlertDescription>
    </Alert>
  ),
};

export const AllStates: Story = {
  render: () => (
    <div className="grid w-[min(90vw,34rem)] gap-3">
      {(["neutral", "info", "success", "warning", "danger"] as const).map(
        (tone) => (
          <Alert key={tone} tone={tone}>
            <AlertTitle>{tone}</AlertTitle>
            <AlertDescription>
              Semantic feedback without a hardcoded brand color.
            </AlertDescription>
          </Alert>
        ),
      )}
    </div>
  ),
};
