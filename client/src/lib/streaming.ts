import { ApiError, parseErrorEnvelope } from "./errors";

const CONVERSATION_DELIMITER = "END_OF_STREAM";

interface StreamEvent {
    type: string;
    content?: unknown;
    error?: unknown;
}

export interface ConversationStreamHandlers {
    onContent?: (text: string) => void;
    onReasoning?: (text: string) => void;
    onReferences?: (references: unknown) => void;
    onArtifact?: (artifact: unknown) => void;
    onTrace?: (trace: unknown) => void;
    onStatus?: (status: string) => void;
}

export interface ConversationStreamResult {
    content: string;
    references?: unknown;
    artifacts: unknown[];
    trace?: unknown;
}

export async function consumeConversationStream(
    stream: ReadableStream<Uint8Array>,
    handlers: ConversationStreamHandlers = {},
): Promise<ConversationStreamResult> {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let content = "";
    let references: unknown;
    const artifacts: unknown[] = [];
    let trace: unknown;
    let completed = false;

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split(CONVERSATION_DELIMITER);
            buffer = parts.pop() ?? "";
            for (const serialized of parts) {
                if (!serialized.trim()) continue;
                const event = parseConversationEvent(serialized);
                switch (event.type) {
                    case "content": {
                        const text = String(event.content ?? "");
                        content += text;
                        handlers.onContent?.(text);
                        break;
                    }
                    case "reasoning":
                        handlers.onReasoning?.(String(event.content ?? ""));
                        break;
                    case "references":
                        references = event.content;
                        handlers.onReferences?.(references);
                        break;
                    case "artifact":
                        artifacts.push(event.content);
                        handlers.onArtifact?.(event.content);
                        break;
                    case "trace":
                        trace = event.content;
                        handlers.onTrace?.(trace);
                        break;
                    case "status":
                        handlers.onStatus?.(String(event.content ?? ""));
                        break;
                    case "complete":
                        completed = true;
                        break;
                    case "error":
                        throw new ApiError(
                            200,
                            parseErrorEnvelope(event.error, { status: 200 }),
                        );
                    default:
                        throw streamProtocolError("stream_event_unknown");
                }
            }
        }
        buffer += decoder.decode();
        if (buffer.trim()) throw streamProtocolError("stream_event_incomplete");
        if (!completed) throw streamProtocolError("stream_incomplete");
        return { content, references, artifacts, trace };
    } finally {
        reader.releaseLock();
    }
}

function parseConversationEvent(serialized: string): StreamEvent {
    let parsed: unknown;
    try {
        parsed = JSON.parse(serialized.trim());
    } catch {
        throw streamProtocolError("stream_event_invalid");
    }
    if (typeof parsed !== "object" || parsed === null || !("type" in parsed)) {
        throw streamProtocolError("stream_event_invalid");
    }
    return parsed as StreamEvent;
}

function streamProtocolError(code: string): ApiError {
    return new ApiError(200, {
        code,
        message: "The response stream ended unexpectedly. Please try again.",
        kind: "dependency_failure",
        retryable: true,
        stage: "client_stream",
    });
}

export interface ServerSentEvent {
    event: string;
    data: unknown;
}

export async function* parseServerSentEvents(
    stream: ReadableStream<Uint8Array>,
): AsyncGenerator<ServerSentEvent> {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
            let boundary = buffer.indexOf("\n\n");
            while (boundary >= 0) {
                const block = buffer.slice(0, boundary);
                buffer = buffer.slice(boundary + 2);
                if (block.trim()) yield parseServerSentEvent(block);
                boundary = buffer.indexOf("\n\n");
            }
        }
        buffer += decoder.decode();
        if (buffer.trim()) throw streamProtocolError("sse_event_incomplete");
    } finally {
        reader.releaseLock();
    }
}

function parseServerSentEvent(block: string): ServerSentEvent {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    try {
        return { event, data: JSON.parse(dataLines.join("\n")) };
    } catch {
        throw streamProtocolError("sse_event_invalid");
    }
}
