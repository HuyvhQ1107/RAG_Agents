import React, { useEffect, useState } from "react";
import {
  apiRequest,
  CitationItem,
  ClarificationOption,
  ConversationDetail,
  TurnItem,
} from "../services/api";
import { sendStreamingChatMessage } from "../services/chatStream";
import { ChatStream } from "../components/ChatStream";
import { ScopeSelector } from "../components/ScopeSelector";

export const ChatPage: React.FC = () => {
  const [conversations, setConversations] = useState<
    Array<{ id: string; title: string }>
  >([]);
  const [activeConv, setActiveConv] = useState<ConversationDetail | null>(null);
  const [question, setQuestion] = useState("");
  const [streamingStage, setStreamingStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadConversations = async () => {
    const data = await apiRequest<{
      items: Array<{ id: string; title: string }>;
    }>("/conversations");
    setConversations(data.items);
    if (!activeConv && data.items.length > 0) {
      await selectConversation(data.items[0].id);
    }
  };

  const selectConversation = async (id: string) => {
    const detail = await apiRequest<ConversationDetail>(`/conversations/${id}`);
    setActiveConv(detail);
  };

  const createNewConversation = async () => {
    const created = await apiRequest<ConversationDetail>("/conversations", {
      method: "POST",
      body: JSON.stringify({}),
    });
    setActiveConv(created);
    await loadConversations();
  };

  useEffect(() => {
    void loadConversations();
  }, []);

  const handleScopeChange = async (
    doc: { id: string; title: string } | null
  ) => {
    if (!activeConv) return;
    await apiRequest(`/conversations/${activeConv.id}`, {
      method: "PATCH",
      body: JSON.stringify({ scope_document_id: doc ? doc.id : null }),
    });
    setActiveConv({
      ...activeConv,
      scope_document_id: doc ? doc.id : null,
      scope_document_title: doc ? doc.title : null,
    });
  };

  const submitMessage = async (
    content: string,
    clarificationChoice?: {
      turn_id?: string;
      option_id: string;
      label?: string;
    } | null
  ) => {
    setError(null);
    let conv = activeConv;
    if (!conv) {
      conv = await apiRequest<ConversationDetail>("/conversations", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setActiveConv(conv);
    }

    const tempTurn: TurnItem = {
      id: `temp-${Date.now()}`,
      ordinal: (conv.turns?.length || 0) + 1,
      question: content,
      kind: "answer",
      answer_language: "vi",
      answer: "",
      assumptions: [],
      missing_parts: [],
      limit_reached: false,
      latency_ms: 0,
      citations: [],
    };

    setActiveConv((prev) =>
      prev ? { ...prev, turns: [...prev.turns, tempTurn] } : prev
    );

    let accumulatedAnswer = "";
    let latestCitations: CitationItem[] = [];

    await sendStreamingChatMessage(
      conv.id,
      { content, clarification_choice: clarificationChoice || null },
      {
        onStarted: (d) => {
          tempTurn.id = d.turn_id;
        },
        onStatus: (stage) => setStreamingStage(stage),
        onClarification: (clar) => {
          setStreamingStage(null);
          setActiveConv((prev) => {
            if (!prev) return prev;
            const updated = prev.turns.map((t) =>
              t.id === tempTurn.id
                ? {
                    ...t,
                    kind: "clarification" as const,
                    answer: clar.question,
                    clarification_options: clar.options,
                  }
                : t
            );
            return { ...prev, turns: updated };
          });
        },
        onDelta: (delta) => {
          accumulatedAnswer += delta;
          setActiveConv((prev) => {
            if (!prev) return prev;
            const updated = prev.turns.map((t) =>
              t.id === tempTurn.id ? { ...t, answer: accumulatedAnswer } : t
            );
            return { ...prev, turns: updated };
          });
        },
        onCitations: (items) => {
          latestCitations = items;
          setActiveConv((prev) => {
            if (!prev) return prev;
            const updated = prev.turns.map((t) =>
              t.id === tempTurn.id ? { ...t, citations: latestCitations } : t
            );
            return { ...prev, turns: updated };
          });
        },
        onCompleted: (done) => {
          setStreamingStage(null);
          setActiveConv((prev) => {
            if (!prev) return prev;
            const updated = prev.turns.map((t) =>
              t.id === tempTurn.id
                ? {
                    ...t,
                    id: done.turn_id,
                    kind: done.kind as TurnItem["kind"],
                    answer_language: done.answer_language,
                    assumptions: done.assumptions,
                    missing_parts: done.missing_parts,
                    limit_reached: done.limit_reached,
                    latency_ms: done.latency_ms,
                  }
                : t
            );
            return { ...prev, turns: updated };
          });
          void loadConversations();
        },
        onError: (err) => {
          setStreamingStage(null);
          setError(err.message);
        },
      }
    );
  };

  return (
    <div className="grid grid-cols-12 gap-4 h-[calc(100vh-4rem)] p-4">
      <aside className="col-span-3 bg-white border rounded-xl p-3 flex flex-col gap-3">
        <button
          type="button"
          onClick={() => void createNewConversation()}
          className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium"
        >
          + Hội thoại mới
        </button>
        <div className="flex-1 overflow-y-auto space-y-1">
          {conversations.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => void selectConversation(c.id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm truncate ${
                activeConv?.id === c.id
                  ? "bg-blue-50 text-blue-800 font-semibold"
                  : "hover:bg-slate-50 text-slate-700"
              }`}
            >
              {c.title}
            </button>
          ))}
        </div>
      </aside>

      <main className="col-span-9 flex flex-col gap-3 h-full">
        <div className="flex items-center justify-between bg-white border rounded-xl p-3">
          <div className="text-sm font-semibold text-slate-800">
            {activeConv?.title || "Hỏi đáp tài liệu nội bộ song ngữ (Việt / Anh)"}
          </div>
          <ScopeSelector
            selectedDocument={
              activeConv?.scope_document_id && activeConv.scope_document_title
                ? {
                    id: activeConv.scope_document_id,
                    title: activeConv.scope_document_title,
                  }
                : null
            }
            onSelectScope={(doc) => void handleScopeChange(doc)}
          />
        </div>

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-xl text-sm">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-3 pr-1">
          <ChatStream
            turns={activeConv?.turns || []}
            streamingStage={streamingStage}
            onSelectClarificationOption={(turnId, opt) =>
              void submitMessage(opt.label, {
                turn_id: turnId,
                option_id: opt.id,
                label: opt.label,
              })
            }
            onSubmitClarificationText={(txt) => void submitMessage(txt)}
          />
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!question.trim()) return;
            const q = question.trim();
            setQuestion("");
            void submitMessage(q);
          }}
          className="flex gap-2 bg-white border rounded-xl p-3"
        >
          <input
            type="text"
            placeholder="Đặt câu hỏi bằng tiếng Việt hoặc tiếng Anh..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="flex-1 border rounded-lg px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={Boolean(streamingStage)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium"
          >
            Gửi câu hỏi
          </button>
        </form>
      </main>
    </div>
  );
};
