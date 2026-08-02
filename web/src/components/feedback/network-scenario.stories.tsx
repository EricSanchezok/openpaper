import { useQuery } from "@tanstack/react-query";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { AsyncBoundary } from "./async-feedback";

type PreviewData = { items: Array<{ id: string; title: string }> };

async function loadPreview(scenario: string): Promise<PreviewData> {
  const response = await fetch(
    `http://localhost:8000/api/v1/foundation-check?scenario=${encodeURIComponent(scenario)}`,
  );
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json() as Promise<PreviewData>;
}

function NetworkPreview({ scenario }: { scenario: string }) {
  const query = useQuery({
    queryKey: ["foundation-preview", scenario],
    queryFn: () => loadPreview(scenario),
    retry: false,
  });

  return (
    <AsyncBoundary
      data={query.data}
      empty={(data) => data.items.length === 0}
      error={query.error}
      loading={query.isPending}
      offline={
        query.error instanceof TypeError &&
        query.error.message === "Failed to fetch"
      }
      retry={() => void query.refetch()}
      retrying={query.isFetching && !query.isPending}
    >
      {(data) => (
        <div className="border-line bg-surface rounded-[var(--radius-lg)] border p-5">
          <p className="text-sm font-medium">{data.items[0]?.title}</p>
          <p className="text-muted mt-1 text-sm">
            Served entirely by Storybook MSW.
          </p>
        </div>
      )}
    </AsyncBoundary>
  );
}

const meta = {
  title: "Examples/Network scenarios",
  parameters: { layout: "padded" },
  render: (_args, context) => (
    <div className="max-w-xl">
      <NetworkPreview
        scenario={`${String(context.globals.network)}-${String(context.globals.data)}`}
      />
    </div>
  ),
  tags: ["autodocs"],
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const ToolbarControlled: Story = {};
export const Slow: Story = { globals: { network: "slow" } };
export const Empty: Story = { globals: { data: "empty" } };
export const ServerError: Story = { globals: { data: "error" } };
export const Offline: Story = { globals: { network: "offline" } };
