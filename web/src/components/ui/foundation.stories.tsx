import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { Button, IconButton } from "./button";
import { Combobox } from "./combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "./dialog";
import { Badge, Progress, Separator, Skeleton } from "./display";
import { Field, FieldMessage, Label } from "./field";
import { Input, SearchField, Textarea } from "./input";
import { Checkbox, RadioGroup, RadioItem, Switch } from "./selection-controls";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs-pagination";

const meta = {
  title: "Examples/Foundation gallery",
  tags: ["autodocs"],
  parameters: { layout: "padded" },
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const AllStates: Story = {
  render: () => (
    <div className="grid max-w-4xl gap-10">
      <section className="grid gap-4">
        <h2 className="text-lg font-semibold">Buttons</h2>
        <div className="flex flex-wrap gap-3">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button loading>Loading</Button>
          <Button disabled>Disabled</Button>
          <IconButton label="Example icon action">+</IconButton>
        </div>
      </section>
      <Separator />
      <section className="grid max-w-xl gap-4">
        <h2 className="text-lg font-semibold">Fields</h2>
        <Field>
          <Label htmlFor="title">Title</Label>
          <Input id="title" placeholder="A concise title" />
          <FieldMessage>Use a title people can scan.</FieldMessage>
        </Field>
        <SearchField aria-label="Search" placeholder="Search" />
        <Textarea
          aria-label="Description"
          placeholder="Long content remains readable inside narrow containers."
        />
        <Field invalid>
          <Label htmlFor="error">Error state</Label>
          <Input aria-invalid id="error" />
          <FieldMessage>This field is required.</FieldMessage>
        </Field>
      </section>
      <Separator />
      <section className="grid gap-4">
        <h2 className="text-lg font-semibold">Selection</h2>
        <div className="flex flex-wrap items-center gap-6">
          <label className="flex items-center gap-2">
            <Checkbox defaultChecked />
            Checkbox
          </label>
          <RadioGroup className="flex gap-4" defaultValue="a">
            <label className="flex items-center gap-2">
              <RadioItem value="a" />
              One
            </label>
            <label className="flex items-center gap-2">
              <RadioItem value="b" />
              Two
            </label>
          </RadioGroup>
          <label className="flex items-center gap-2">
            <Switch defaultChecked />
            Enabled
          </label>
        </div>
        <div className="grid max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
          <Select defaultValue="en">
            <SelectTrigger aria-label="Language">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="en">English</SelectItem>
              <SelectItem value="zh-CN">简体中文</SelectItem>
            </SelectContent>
          </Select>
          <Combobox
            options={[
              { label: "Default", value: "default" },
              {
                label: "A very long option to test constrained layouts",
                value: "long",
              },
            ]}
            value="default"
          />
        </div>
      </section>
      <Separator />
      <section className="grid gap-4">
        <h2 className="text-lg font-semibold">Display and navigation</h2>
        <div className="flex flex-wrap gap-2">
          <Badge>Neutral</Badge>
          <Badge tone="info">Info</Badge>
          <Badge tone="success">Success</Badge>
          <Badge tone="warning">Warning</Badge>
          <Badge tone="danger">Danger</Badge>
        </div>
        <Progress aria-label="Progress" value={42} />
        <Skeleton className="h-20" />
        <Tabs defaultValue="one">
          <TabsList>
            <TabsTrigger value="one">One</TabsTrigger>
            <TabsTrigger value="two">Two</TabsTrigger>
          </TabsList>
          <TabsContent className="pt-4" value="one">
            First panel
          </TabsContent>
          <TabsContent className="pt-4" value="two">
            Second panel
          </TabsContent>
        </Tabs>
      </section>
    </div>
  ),
};

export const KeyboardDialog: Story = {
  render: () => (
    <Dialog>
      <DialogTrigger asChild>
        <Button>Open dialog</Button>
      </DialogTrigger>
      <DialogContent closeLabel="Close dialog">
        <DialogTitle>Isolated interaction</DialogTitle>
        <DialogDescription>
          This dialog can be opened, focused, and dismissed without a product
          page.
        </DialogDescription>
        <Input className="mt-5" placeholder="Focusable field" />
      </DialogContent>
    </Dialog>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Open dialog" }));
    await expect(within(document.body).getByRole("dialog")).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await expect(
      within(document.body).queryByRole("dialog"),
    ).not.toBeInTheDocument();
  },
};

export const NarrowLongContent: Story = {
  globals: { viewport: { value: "narrowPanel", isRotated: false } },
  render: () => (
    <div className="max-w-sm">
      <Button className="w-full">
        A deliberately long localized action label that must remain usable
      </Button>
    </div>
  ),
};
