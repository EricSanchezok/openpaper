export type AuthChannelEvent = "signed-in" | "signed-out";

const channelName = "scholens-auth-events";

export function publishAuthEvent(event: AuthChannelEvent) {
  if (typeof BroadcastChannel === "undefined") return;
  const channel = new BroadcastChannel(channelName);
  channel.postMessage(event);
  channel.close();
}

export function subscribeToAuthEvents(
  listener: (event: AuthChannelEvent) => void,
) {
  if (typeof BroadcastChannel === "undefined") return () => undefined;
  const channel = new BroadcastChannel(channelName);
  channel.onmessage = (event: MessageEvent<AuthChannelEvent>) => {
    if (event.data === "signed-in" || event.data === "signed-out") {
      listener(event.data);
    }
  };
  return () => channel.close();
}
