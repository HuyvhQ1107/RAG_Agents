import { CitationItem, ClarificationOption } from "./api";

export interface StreamEventHandlers {
  onStarted?: (data: {
    turn_id: string;
    trace_id: string;
    scope_document?: { id: string; title: string } | null;
  }) => void;
  onStatus?: (stage: string) => void;
  onClarification?: (data: {
    question: string;
    options: ClarificationOption[];
    allow_free_text: boolean;
    remaining_clarifications: number;
  }) => void;
  onDelta?: (deltaText: string) => void;
  onCitations?: (items: CitationItem[]) => void;
  onCompleted?: (data: {
    turn_id: string;
    kind: string;
    answer_language: "vi" | "en";
    assumptions: string[];
    missing_parts: string[];
    limit_reached: boolean;
    latency_ms: number;
  }) => void;
  onError?: (err: {
    code: string;
    message: string;
    retryable: boolean;
  }) => void;
}

export function parseSseBlock(block: string): {
  event: string;
  data: Record<string, unknown>;
} | null {
  const trimmed = block.trim();
  if (!trimmed || trimmed.startsWith(":")) {
    return null;
  }
  let eventName = "";
  let dataStr = "";
  for (const line of trimmed.split("\n")) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataStr += line.slice(5).trim();
    }
  }
  if (!eventName || !dataStr) {
    return null;
  }
  try {
    return { event: eventName, data: JSON.parse(dataStr) };
  } catch {
    return null;
  }
}

export async function sendStreamingChatMessage(
  conversationId: string,
  payload: {
    content: string;
    clarification_choice?: { turn_id?: string; option_id: string; label?: string } | null;
  },
  handlers: StreamEventHandlers,
  signal?: AbortSignal
): Promise<void> {
  const resp = await fetch(`/api/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
    signal,
  });

  if (!resp.ok || !resp.body) {
    const errBody = await resp.json().catch(() => ({}));
    const errObj = errBody?.error || {};
    handlers.onError?.({
      code: errObj.code || `http_${resp.status}`,
      message: errObj.message || "Không thể gửi câu hỏi.",
      retryable: true,
    });
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      const parsed = parseSseBlock(part);
      if (!parsed) continue;
      const { event, data } = parsed;
      if (event === "turn.started") {
        handlers.onStarted?.(data as never);
      } else if (event === "status") {
        handlers.onStatus?.(String(data.stage || ""));
      } else if (event === "clarification") {
        handlers.onClarification?.(data as never);
      } else if (event === "answer.delta") {
        handlers.onDelta?.(String(data.text || ""));
      } else if (event === "citations") {
        handlers.onCitations?.((data.items as CitationItem[]) || []);
      } else if (event === "turn.completed") {
        handlers.onCompleted?.(data as never);
      } else if (event === "error") {
        handlers.onError?.(data as never);
      }
    }
  }
}
